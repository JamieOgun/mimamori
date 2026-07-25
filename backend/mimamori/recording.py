"""Download and persist Twilio call recordings for later review/scoring."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

import httpx

from . import config

logger = logging.getLogger("mimamori.recording")

_SID_PATTERN = re.compile(r"^[A-Z]{2}[0-9a-fA-F]{32}$")


def _validate_sid(name: str, value: str) -> None:
    if not _SID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {name}: {value!r}")


def recording_media_url(recording_sid: str) -> str:
    """Return the Twilio MP3 media URL for a recording SID."""
    config.require("TWILIO_ACCOUNT_SID")
    _validate_sid("recording_sid", recording_sid)
    return (
        "https://api.twilio.com/2010-04-01/Accounts/"
        f"{config.TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.mp3"
    )


async def download_recording(
    *,
    call_sid: str,
    recording_sid: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Download a completed Twilio recording to ``RECORDING_DIR``.

    Returns:
        The path written.
    """
    _validate_sid("call_sid", call_sid)
    _validate_sid("recording_sid", recording_sid)

    os.makedirs(config.RECORDING_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(
        config.RECORDING_DIR,
        f"{stamp}_{call_sid}_{recording_sid}.mp3",
    )

    close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=30)

    try:
        response = await client.get(
            recording_media_url(recording_sid),
            auth=config.twilio_http_auth(),
        )
        response.raise_for_status()
        with open(path, "wb") as fh:
            fh.write(response.content)
    finally:
        if close_client:
            await client.aclose()

    logger.info("Saved recording -> %s", path)
    return path
