"""Scoring graders for the MimaMori transcript analysis pipeline.

Aligned with the frontend scoring model (``frontend/src/data/calls.ts``):

- Scores run **0-100 where higher means HEALTHIER** (100 = no concern, low =
  concerning). This is the inverse of a "risk score" — a normal, warm chat scores
  near 100.
- Each dimension is rated per-criterion; the dimension score and overall score
  are computed as means in :mod:`mimamori.score.pipeline`, and ``risk`` is banded
  (>=80 Low, >=65 Watch, <65 High) — matching the dashboard exactly.
- The graders are deliberately **strict about staying high**: they only deduct on
  clear, quotable evidence, so ordinary calls don't get flagged.

Criterion names are camelCase to match the frontend keys verbatim.
"""

from __future__ import annotations

from typing import Final

from mimamori import config
from mimamori.score.grader import create_score_grader

# --- Criteria (frontend keys) --------------------------------------------
# Higher score = healthier / no problem on this axis.
COGNITIVE_CRITERIA: Final[dict[str, str]] = {
    "repetition": "100 = no repeated stories/questions; low = repeats the same thing within the call.",
    "temporalConfusion": "100 = accurate about day/date/season/timeline; low = confused about when things are.",
    "wordFinding": "100 = fluent word retrieval; low = long pauses, 'that thing', talking around words.",
    "confabulation": "100 = consistent, plausible details; low = fabricated or self-contradictory claims.",
    "vocabulary": "100 = rich, varied language; low = markedly simplified or limited.",
    "coherence": "100 = organized and easy to follow; low = disorganized or tangential.",
}

EMOTIONAL_CRITERIA: Final[dict[str, str]] = {
    "affect": "100 = warm, expressive, engaged; low = flat, listless, monotone.",
    "anxiety": "100 = calm and settled; low = anxious, worried, fearful.",
    "withdrawal": "100 = socially engaged and willing to talk; low = withdrawn, avoidant.",
    "interest": "100 = interested in and looking forward to activities; low = loss of interest.",
    "overallMood": "100 = positive mood; low = sad, hopeless, lonely, or negative self-talk.",
}


def _criteria_block(criteria: dict[str, str]) -> str:
    """Render criteria as a bulleted ``key: description`` list for the prompt."""
    return "\n".join(f"- {key}: {desc}" for key, desc in criteria.items())


def format_transcript(turns: list[dict[str, str]]) -> str:
    """Render transcript turns as a readable script for the template.

    Args:
        turns: The ``turns`` list from a saved transcript JSON file; each item
            has ``role`` ("assistant"/"user") and ``text``.

    Returns:
        A newline-separated script, one turn per line.
    """
    return "\n".join(f"{t['role']}: {t['text']}" for t in turns if t.get("text"))


# --- Shared strict rubric + output contract ------------------------------
_STRICTNESS: Final[str] = """\
Scoring is STRICT and conservative — err toward HEALTHY:
- Assume health by default. An ordinary, warm, unremarkable conversation scores
  85-100 on every criterion.
- Only lower a criterion when the transcript has clear, quotable evidence of a
  real problem. Do NOT infer problems from brevity, politeness, saying goodbye,
  a short call, or a single ambiguous remark.
- If a criterion cannot be judged from the transcript (too little to go on),
  score it 90 — do not guess low.
- Reserve scores below 60 for unmistakable, repeated, or severe evidence.
- Judge only the "user" (elderly person) turns; "assistant" is the AI companion."""


def _json_contract(criteria: dict[str, str]) -> str:
    """The shared output contract, parameterized by the criteria set."""
    keys = ", ".join(f'"{k}"' for k in criteria)
    return f"""\
Respond with a SINGLE JSON object and nothing else — no markdown, no code
fences, no commentary. Use exactly this shape:

{{
  "criteria": {{ {keys}: <integer 0-100, higher = healthier> }},
  "markers": [<criterion keys with a genuine concern; empty if none>],
  "notes": "<1-2 sentences of plain-language reasoning; quote a short piece of
             evidence if you flagged anything; write in the conversation's
             primary language>"
}}

Every criterion below must appear in "criteria".

Criteria:
{_criteria_block(criteria)}"""


# --- Cognitive grader -----------------------------------------------------
COGNITIVE_GRADER = create_score_grader(
    name="cognitive criteria grader",
    model=config.AIAND_MODEL,
    temperature=0.0,
    reasoning_effort=None,
    seed=42,
    developer_prompt=f"""
You are a clinical-adjacent analyst reviewing a transcript of a friendly morning
phone call with an elderly person. This is NOT a medical diagnosis — you rate
cognitive criteria so a family member can notice change over time.

{_STRICTNESS}

{_json_contract(COGNITIVE_CRITERIA)}
""",
    template_prompt="""
Rate the cognitive criteria for the following morning-call transcript.

<transcript>
{{item.transcript}}
</transcript>
""",
    score_range=(0, 100),
)


# --- Emotional grader -----------------------------------------------------
EMOTIONAL_GRADER = create_score_grader(
    name="emotional criteria grader",
    model=config.AIAND_MODEL,
    temperature=0.0,
    reasoning_effort=None,
    seed=42,
    developer_prompt=f"""
You are a clinical-adjacent analyst reviewing a transcript of a friendly morning
phone call with an elderly person. This is NOT a medical diagnosis — you rate
emotional wellbeing criteria so a family member can notice change over time.

{_STRICTNESS}

{_json_contract(EMOTIONAL_CRITERIA)}
""",
    template_prompt="""
Rate the emotional wellbeing criteria for the following morning-call transcript.

<transcript>
{{item.transcript}}
</transcript>
""",
    score_range=(0, 100),
)
