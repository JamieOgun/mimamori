"""Configuration for the MimaMori outbound-call service.

Loads settings from the environment (see ``.env.example``). Keeping this in one
place means the FastAPI server, the CLI trigger, and any future cron entrypoint
all read the same source of truth.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# --- Twilio ---------------------------------------------------------------
# Two supported auth styles:
#   1. Account SID (AC...) + Auth Token.
#   2. API Key SID (SK...) + API Key Secret, PLUS the Account SID (AC...).
# The account SID (AC...) is always required to identify the account.
TWILIO_ACCOUNT_SID: str | None = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN: str | None = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_API_KEY_SID: str | None = os.getenv("TWILIO_API_KEY_SID")
# Accept the legacy TWILIO_CLIENT_SECRET name for the API key secret.
TWILIO_API_KEY_SECRET: str | None = os.getenv("TWILIO_API_KEY_SECRET") or os.getenv(
    "TWILIO_CLIENT_SECRET"
)

# Backfill: if someone put an API key (SK...) into TWILIO_ACCOUNT_SID by
# mistake, route it to the API-key field so the AC account SID stays distinct.
if TWILIO_ACCOUNT_SID and TWILIO_ACCOUNT_SID.startswith("SK"):
    TWILIO_API_KEY_SID = TWILIO_API_KEY_SID or TWILIO_ACCOUNT_SID
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_AC_SID")  # the real AC... SID, if set

# The Twilio number the call is placed *from* (E.164, e.g. +81501234567).
PHONE_NUMBER_FROM: str | None = os.getenv("PHONE_NUMBER_FROM")

# Explicit allowlist of destination numbers this service may call (E.164,
# comma-separated). On a Full account there is no "verified caller ID" gate, so
# this is our own guardrail against dialing anything unintended. Enrolled
# elderly numbers go here (or in the DB later). Empty => fall back to the
# Twilio-owned / verified-caller-ID check only.
ALLOWED_DESTINATIONS: set[str] = {
    n.strip() for n in os.getenv("ALLOWED_DESTINATIONS", "").split(",") if n.strip()
}


def twilio_client_args() -> tuple:
    """Return positional args for ``twilio.rest.Client`` for either auth style.

    Returns:
        A tuple suitable for ``Client(*args)``.

    Raises:
        RuntimeError: If no usable credential combination is present.
    """
    if TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET and TWILIO_ACCOUNT_SID:
        return (TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET, TWILIO_ACCOUNT_SID)
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        return (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    raise RuntimeError(
        "Twilio auth incomplete. Provide either TWILIO_ACCOUNT_SID (AC...) + "
        "TWILIO_AUTH_TOKEN, or TWILIO_API_KEY_SID (SK...) + TWILIO_API_KEY_SECRET "
        "+ TWILIO_ACCOUNT_SID (AC...). See .env.example."
    )


# --- AI& inference (scoring pipeline) -------------------------------------
# AI& exposes an OpenAI-compatible endpoint that serves open models
# (gpt-oss, deepseek, glm, qwen). The scorers under mimamori/score/ talk to it
# through the shared client in score/client.py.
AIAND_API_KEY: str | None = os.getenv("AIAND_API_KEY")
AIAND_BASE_URL: str = os.getenv("AIAND_BASE_URL", "https://api.aiand.com/v1")
# Default model for scoring; individual scorers may override per request.
AIAND_MODEL: str = os.getenv("AIAND_MODEL", "openai/gpt-oss-120b")
AIAND_SCORING_MODELS: list[str] = [
    model.strip()
    for model in os.getenv(
        "AIAND_SCORING_MODELS",
        f"{AIAND_MODEL},qwen/qwen3.6-27b,zai-org/glm-5.2",
    ).split(",")
    if model.strip()
]
AIAND_SCORING_MIN_MODELS: int = int(os.getenv("AIAND_SCORING_MIN_MODELS", "2"))

# --- OpenAI ---------------------------------------------------------------
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
# gpt-realtime-2.1-mini is the model the MimaMori spec targets (~$0.016/min).
REALTIME_MODEL: str = os.getenv("REALTIME_MODEL", "gpt-realtime-2.1-mini")
# Voice used by the Realtime API. "alloy" is neutral; "shimmer"/"marin" are
# warmer options that suit an elderly companion persona.
VOICE: str = os.getenv("REALTIME_VOICE", "shimmer")
TEMPERATURE: float = float(os.getenv("REALTIME_TEMPERATURE", "0.8"))

# --- Networking -----------------------------------------------------------
# Public host that Twilio can reach (your ngrok domain, no protocol prefix).
# e.g. "abcd-1-2-3-4.ngrok-free.app"
DOMAIN: str = (os.getenv("DOMAIN") or "").strip().rstrip("/")
# Strip any protocol a user may have pasted in by mistake.
for _prefix in ("https://", "http://", "wss://", "ws://"):
    if DOMAIN.startswith(_prefix):
        DOMAIN = DOMAIN[len(_prefix) :]

PORT: int = int(os.getenv("PORT", "6060"))

# Where captured transcripts are written for the scoring pipeline to consume.
TRANSCRIPT_DIR: str = os.getenv(
    "TRANSCRIPT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "transcripts"),
)

# Where Twilio call recordings are downloaded after Twilio finishes processing.
RECORDING_DIR: str = os.getenv(
    "RECORDING_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "recordings"),
)

# --- Caregiver escalation -------------------------------------------------
# TODO: Confirm production escalation thresholds with the care team before
# customer use. The defaults match the current High-risk scoring band.
ESCALATION_ENABLED: bool = os.getenv("ESCALATION_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
}
ESCALATION_SCORE_BELOW: int = int(os.getenv("ESCALATION_SCORE_BELOW", "65"))
ESCALATION_RISK_LEVELS: set[str] = {
    level.strip()
    for level in os.getenv("ESCALATION_RISK_LEVELS", "High").split(",")
    if level.strip()
}
CAREGIVER_EMAIL: str = os.getenv(
    "CAREGIVER_EMAIL", "jamieogundiran@gmail.com"
).strip()
EMAIL_FROM: str = os.getenv("EMAIL_FROM", "").strip()
SMTP_HOST: str = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() in {
    "1",
    "true",
    "yes",
}
DASHBOARD_BASE_URL: str = os.getenv("DASHBOARD_BASE_URL", "http://localhost:3000")


def twilio_http_auth() -> tuple[str, str]:
    """Return Basic Auth credentials for Twilio REST API HTTP requests."""
    if TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET:
        return (TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET)
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        return (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    raise RuntimeError(
        "Twilio auth incomplete. Provide credentials before downloading recordings."
    )


def require(*names: str) -> None:
    """Raise if any named config value is unset.

    Args:
        *names: Names of module-level settings that must be truthy.

    Raises:
        RuntimeError: If any named setting is missing, listing all that are.
    """
    missing = [name for name in names if not globals().get(name)]
    if missing:
        raise RuntimeError(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Set them in backend/.env (see .env.example)."
        )
