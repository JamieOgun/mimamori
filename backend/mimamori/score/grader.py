"""LLM-as-judge score graders for the scoring pipeline.

A :class:`ScoreGrader` bundles the model config and the two prompt halves —
``developer_prompt`` (the rubric, sent as the system message) and
``template_prompt`` (the per-item message, with ``{{item.<field>}}`` slots) —
plus the valid ``score_range``. Grader definitions live in ``prompt.py``; this
module just holds the reusable machinery and the AI& call.

``create_score_grader`` is our own thin factory (the OpenAI SDK ships the
``score_model_grader`` *types* but no such constructor), matching the shape used
across the project's graders.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from mimamori.score import client

logger = logging.getLogger(__name__)

# Matches {{item.field}} with optional surrounding whitespace.
_TEMPLATE_RE = re.compile(r"\{\{\s*item\.([a-zA-Z0-9_]+)\s*\}\}")


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object out of a model reply.

    Open models sometimes wrap JSON in ``` fences or add stray prose, so we
    strip fences and slice from the first ``{`` to the last ``}``.

    Raises:
        ValueError: If no JSON object can be located or parsed.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in grader output: {text!r}")
    return json.loads(text[start : end + 1])


@dataclass(frozen=True)
class ScoreGrader:
    """An LLM-as-judge grader: model config plus a rubric and item template."""

    name: str
    model: str
    developer_prompt: str
    template_prompt: str
    score_range: tuple[int, int]
    temperature: float = 0.0
    reasoning_effort: str | None = None
    seed: int | None = None

    def render(self, item: dict[str, Any]) -> str:
        """Fill the ``template_prompt`` from an ``item`` mapping.

        Args:
            item: Values for the ``{{item.<field>}}`` placeholders.

        Raises:
            KeyError: If the template references a field absent from ``item``.
        """

        def _sub(match: re.Match[str]) -> str:
            field = match.group(1)
            if field not in item:
                raise KeyError(f"Template field {field!r} missing from item")
            return str(item[field])

        return _TEMPLATE_RE.sub(_sub, self.template_prompt)

    async def grade(
        self, item: dict[str, Any], *, model: str | None = None
    ) -> dict[str, Any]:
        """Run the grader against ``item`` and return the parsed JSON verdict.

        Args:
            item: Values for the template placeholders (e.g. ``{"transcript": ...}``).
            model: Optional per-call model override; defaults to ``self.model``.

        Returns:
            The parsed grader output. If it contains a numeric ``score``, that
            value is clamped into ``score_range``.
        """
        request: dict[str, Any] = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": self.developer_prompt},
                {"role": "user", "content": self.render(item)},
            ],
            "temperature": self.temperature,
        }
        # Only send optional params when set — some open models reject unknowns.
        if self.seed is not None:
            request["seed"] = self.seed
        if self.reasoning_effort is not None:
            request["reasoning_effort"] = self.reasoning_effort

        response = await client.get_client().chat.completions.create(**request)
        result = _extract_json(response.choices[0].message.content or "")

        lo, hi = self.score_range

        def _clamp(value: Any) -> Any:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return max(lo, min(hi, value))
            return value

        # Clamp a top-level "score" and/or every value in a "criteria" map.
        if "score" in result:
            result["score"] = _clamp(result["score"])
        criteria = result.get("criteria")
        if isinstance(criteria, dict):
            result["criteria"] = {k: _clamp(v) for k, v in criteria.items()}
        return result


def create_score_grader(
    *,
    name: str,
    model: str,
    developer_prompt: str,
    template_prompt: str,
    score_range: tuple[int, int],
    temperature: float = 0.0,
    reasoning_effort: str | None = None,
    seed: int | None = None,
) -> ScoreGrader:
    """Construct a :class:`ScoreGrader` (keyword-only, mirroring the eval API).

    Args:
        name: Human-readable grader name (for logs/eval reports).
        model: Model id to grade with.
        developer_prompt: Rubric/instructions, sent as the system message.
        template_prompt: Per-item message with ``{{item.<field>}}`` slots.
        score_range: Inclusive ``(min, max)`` bounds for the score.
        temperature: Sampling temperature; 0.0 for reproducible grading.
        reasoning_effort: Reasoning effort for models that support it, else None.
        seed: Sampling seed for reproducibility, if the model honors it.

    Returns:
        A configured, ready-to-run grader.
    """
    return ScoreGrader(
        name=name,
        model=model,
        developer_prompt=developer_prompt.strip(),
        template_prompt=template_prompt.strip(),
        score_range=score_range,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        seed=seed,
    )
