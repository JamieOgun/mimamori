"""Scores a saved transcript and persists the result back into its JSON file.

Runs the cognitive and emotional graders in parallel, then aggregates their
per-criterion ratings into the frontend's scoring shape
(``frontend/src/data/calls.ts``): a dimension ``score`` is the mean of its
criteria, the overall ``score`` is the mean of the two dimensions, and ``risk``
is banded from the *worse* dimension (so a single-axis decline isn't masked by a
healthy other axis). All aggregation is deterministic Python — the LLM only
rates individual criteria.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from mimamori import config
from mimamori.score.grader import ScoreGrader
from mimamori.score.prompt import (
    COGNITIVE_CRITERIA,
    COGNITIVE_GRADER,
    EMOTIONAL_CRITERIA,
    EMOTIONAL_GRADER,
    format_transcript,
)

logger = logging.getLogger(__name__)

# Missing/unjudged criteria default to healthy, per the strict rubric.
_DEFAULT_CRITERION = 90

# Risk bands on the 0-100 (higher = healthier) overall score, matching the
# frontend's scoreTone thresholds.
_RISK_LOW = 80
_RISK_WATCH = 65


def _mean(values: list[int]) -> int:
    """Rounded integer mean (0 for an empty list)."""
    return round(sum(values) / len(values)) if values else 0


def _risk(score: int) -> str:
    """Band a 0-100 score into Low / Watch / High (higher = healthier)."""
    if score >= _RISK_LOW:
        return "Low"
    if score >= _RISK_WATCH:
        return "Watch"
    return "High"


def _assess(raw: dict[str, Any], criteria: dict[str, str]) -> dict[str, Any]:
    """Shape one grader's raw output into a frontend ``Assessment``.

    Fills any criterion the model omitted with the healthy default, computes the
    dimension score as the criteria mean, and carries markers/notes through.
    """
    scored = {
        name: int(raw.get("criteria", {}).get(name, _DEFAULT_CRITERION))
        for name in criteria
    }
    return {
        "score": _mean(list(scored.values())),
        "criteria": scored,
        "markers": raw.get("markers", []),
        "notes": raw.get("notes", ""),
    }


async def _grade_one_model(
    *,
    grader: ScoreGrader,
    criteria: dict[str, str],
    transcript: str,
    model: str,
) -> tuple[str, dict[str, Any]]:
    """Grade one dimension with one model and normalize the raw result."""
    raw = await grader.grade({"transcript": transcript}, model=model)
    return model, _assess(raw, criteria)


async def _grade_dimension_ensemble(
    *,
    grader: ScoreGrader,
    criteria: dict[str, str],
    transcript: str,
) -> dict[str, Any]:
    """Grade one dimension with every configured model and average criteria."""
    models = config.AIAND_SCORING_MODELS or [config.AIAND_MODEL]
    min_models = max(1, min(config.AIAND_SCORING_MIN_MODELS, len(models)))
    results = await asyncio.gather(
        *(
            _grade_one_model(
                grader=grader,
                criteria=criteria,
                transcript=transcript,
                model=model,
            )
            for model in models
        ),
        return_exceptions=True,
    )

    model_scores: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for model, result in zip(models, results, strict=True):
        if isinstance(result, Exception):
            failures[model] = str(result)
            continue
        scored_model, assessment = result
        model_scores[scored_model] = assessment

    if len(model_scores) < min_models:
        failure_text = "; ".join(
            f"{model}: {error}" for model, error in failures.items()
        )
        raise RuntimeError(
            f"{grader.name} needs at least {min_models} successful model scores; "
            f"got {len(model_scores)}. Failures: {failure_text or 'none'}"
        )

    if failures:
        logger.warning(
            "%s ensemble continued with %d/%d successful models; failures=%s",
            grader.name,
            len(model_scores),
            len(models),
            failures,
        )

    averaged_criteria = {
        name: _mean([score["criteria"][name] for score in model_scores.values()])
        for name in criteria
    }
    markers = [
        name
        for name in criteria
        if any(name in score.get("markers", []) for score in model_scores.values())
    ]
    notes = "\n".join(
        f"{model}: {score['notes']}"
        for model, score in model_scores.items()
        if score.get("notes")
    )

    return {
        "score": _mean(list(averaged_criteria.values())),
        "criteria": averaged_criteria,
        "markers": markers,
        "notes": notes,
        "model_scores": model_scores,
        "model_failures": failures,
    }


async def score_transcript(data: dict[str, Any]) -> dict[str, Any]:
    """Run both graders over a transcript payload and aggregate to the UI shape.

    Args:
        data: A loaded transcript JSON (must contain ``turns``).

    Returns:
        A scores block: overall ``score``/``risk`` plus ``cognitive`` and
        ``emotional`` assessments, the model used, and a UTC timestamp.
    """
    transcript = format_transcript(data["turns"])
    cognitive, emotional = await asyncio.gather(
        _grade_dimension_ensemble(
            grader=COGNITIVE_GRADER,
            criteria=COGNITIVE_CRITERIA,
            transcript=transcript,
        ),
        _grade_dimension_ensemble(
            grader=EMOTIONAL_GRADER,
            criteria=EMOTIONAL_CRITERIA,
            transcript=transcript,
        ),
    )
    overall = _mean([cognitive["score"], emotional["score"]])
    model_scores = {
        "cognitive": cognitive.pop("model_scores"),
        "emotional": emotional.pop("model_scores"),
    }
    model_failures = {
        "cognitive": cognitive.pop("model_failures"),
        "emotional": emotional.pop("model_failures"),
    }
    # Risk is banded from the WORSE dimension so a single-axis decline (e.g.
    # cognitive) isn't masked by a healthy other axis in the overall mean.
    return {
        "score": overall,
        "risk": _risk(min(cognitive["score"], emotional["score"])),
        "cognitive": cognitive,
        "emotional": emotional,
        "model": "ensemble",
        "models": config.AIAND_SCORING_MODELS or [config.AIAND_MODEL],
        "minimum_successful_models": max(
            1,
            min(
                config.AIAND_SCORING_MIN_MODELS,
                len(config.AIAND_SCORING_MODELS or [config.AIAND_MODEL]),
            ),
        ),
        "model_scores": model_scores,
        "model_failures": model_failures,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


async def score_transcript_file(path: str) -> dict[str, Any]:
    """Load a transcript JSON, score it, write the scores back, and return them.

    Args:
        path: Path to a transcript JSON file written by ``transcript.py``.

    Returns:
        The scores block that was persisted under the file's ``scores`` key.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    scores = await score_transcript(data)
    data["scores"] = scores

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)

    logger.info(
        "Scored %s -> overall=%s risk=%s (cognitive=%s emotional=%s)",
        path,
        scores["score"],
        scores["risk"],
        scores["cognitive"]["score"],
        scores["emotional"]["score"],
    )
    return scores
