"""Captures a call transcript and persists it for the scoring pipeline.

The OpenAI Realtime API emits transcription events for both sides of the
conversation. We accumulate them in order and write a single JSON file per call,
which is the exact input the downstream cognitive/emotional scoring step reads.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config

logger = logging.getLogger("mimamori.transcript")


def find_transcript(call_sid: str) -> str | None:
    """Return the saved transcript path for a call SID, if one exists.

    Files are named ``{stamp}_{call_sid}.json``; if a call somehow produced more
    than one, the most recent (highest timestamp) is returned.

    Args:
        call_sid: The Twilio call SID to look up.

    Returns:
        The transcript file path, or None if none has been written yet.
    """
    matches = sorted(
        glob.glob(os.path.join(config.TRANSCRIPT_DIR, f"*_{call_sid}.json"))
    )
    return matches[-1] if matches else None


@dataclass
class Turn:
    """One utterance in the conversation."""

    role: str  # "assistant" (the AI) or "user" (the elderly person)
    text: str
    at: str  # ISO-8601 UTC timestamp


@dataclass
class CallTranscript:
    """Accumulates turns during a call and writes them out when it ends."""

    call_sid: str
    to_number: str | None = None
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    turns: list[Turn] = field(default_factory=list)

    def add(self, role: str, text: str) -> None:
        """Append a turn if it has non-empty content."""
        text = (text or "").strip()
        if not text:
            return
        self.turns.append(
            Turn(role=role, text=text, at=datetime.now(timezone.utc).isoformat())
        )

    def save(self) -> str | None:
        """Write the transcript to ``TRANSCRIPT_DIR`` as JSON.

        Returns:
            The path written, or None if there were no turns to save.
        """
        if not self.turns:
            logger.warning("No transcript turns captured for call %s", self.call_sid)
            return None

        os.makedirs(config.TRANSCRIPT_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(config.TRANSCRIPT_DIR, f"{stamp}_{self.call_sid}.json")
        payload = {
            "call_sid": self.call_sid,
            "to_number": self.to_number,
            "started_at": self.started_at,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "turns": [turn.__dict__ for turn in self.turns],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        logger.info("Saved transcript (%d turns) -> %s", len(self.turns), path)
        return path
