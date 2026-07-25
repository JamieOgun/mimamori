"""Read scored transcripts and shape them for the frontend dashboard.

The scoring pipeline writes one JSON file per call into ``TRANSCRIPT_DIR`` with
a ``scores`` block (see ``score/pipeline.py``). The dashboard needs a *list* of
those calls plus each call's turns, so this module reads the files and reshapes
them into the JSON the Next.js app consumes (``frontend/src/data/calls.ts``),
deriving the call duration and per-turn timestamps from the stored ISO times.

Only the quantitative half of a ``CallRecord`` is produced here — score, risk,
criteria, transcript text, and duration. The presentational/i18n fields
(translation keys, evidence markers, transcript flags, recording label) are not
in the transcript data and stay hardcoded on the frontend.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from datetime import datetime
from typing import Any

from . import config

logger = logging.getLogger("mimamori.calls")

# Transcript role -> the frontend's speaker label.
_SPEAKER = {"assistant": "MimaMori", "user": "Recipient"}


def _parse(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z``."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clock(seconds: float) -> str:
    """Format a non-negative number of seconds as ``MM:SS``."""
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _shape(data: dict[str, Any], call_sid: str) -> dict[str, Any] | None:
    """Reshape one loaded transcript into the frontend's call shape.

    Args:
        data: A transcript JSON loaded from ``TRANSCRIPT_DIR``.
        call_sid: The call SID (used as the record ``id``).

    Returns:
        The shaped call dict, or None if the transcript has not been scored yet.
    """
    scores = data.get("scores")
    if not scores:
        return None

    started = _parse(data.get("started_at", ""))
    ended = _parse(data.get("ended_at", ""))
    duration = int((ended - started).total_seconds()) if started and ended else 0

    transcript = []
    for turn in data.get("turns", []):
        at = _parse(turn.get("at", ""))
        offset = (at - started).total_seconds() if at and started else 0
        transcript.append(
            {
                "time": _clock(offset),
                "speaker": _SPEAKER.get(turn.get("role", ""), "Recipient"),
                "text": turn.get("text", ""),
            }
        )

    return {
        "id": call_sid,
        "toNumber": data.get("to_number"),
        "score": scores.get("score", 0),
        "risk": scores.get("risk", "Low"),
        "durationMinutes": duration // 60,
        "durationSeconds": duration % 60,
        "cognitive": _dimension(scores.get("cognitive", {})),
        "emotional": _dimension(scores.get("emotional", {})),
        "transcript": transcript,
        "startedAt": data.get("started_at"),
    }


def _dimension(raw: dict[str, Any]) -> dict[str, Any]:
    """Shape one scored dimension (cognitive/emotional) for the frontend."""
    return {
        "score": raw.get("score", 0),
        "criteria": raw.get("criteria", {}),
        # Real grader output — short evidence labels and a prose note.
        "markers": raw.get("markers", []),
        "notes": raw.get("notes", ""),
    }


def _sid_from_path(path: str) -> str:
    """Recover the call SID from a ``{stamp}_{call_sid}.json`` filename."""
    stem = os.path.basename(path).removesuffix(".json")
    _, _, sid = stem.partition("_")
    return sid or stem


def list_calls() -> list[dict[str, Any]]:
    """List every scored call, newest first (by call start time)."""
    calls = []
    for path in glob.glob(os.path.join(config.TRANSCRIPT_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable transcript %s: %s", path, exc)
            continue
        shaped = _shape(data, data.get("call_sid") or _sid_from_path(path))
        if shaped:
            calls.append(shaped)

    calls.sort(key=lambda call: call.get("startedAt") or "", reverse=True)
    return calls


def get_call(call_sid: str) -> dict[str, Any] | None:
    """Return one scored call by SID, or None if it isn't scored yet."""
    from .transcript import find_transcript

    path = find_transcript(call_sid)
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return _shape(data, call_sid)
