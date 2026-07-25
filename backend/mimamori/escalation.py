"""Caregiver escalation for high-risk check-in results.

The scoring pipeline writes results into the transcript JSON. This module reads
that same file, decides whether a caregiver alert is required, sends a bilingual
email, and writes an ``escalation`` block back to the transcript for idempotency.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from . import config

logger = logging.getLogger("mimamori.escalation")


def should_escalate(scores: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return whether scores cross the configured escalation threshold."""
    reasons: list[str] = []
    risk = str(scores.get("risk", ""))
    score = int(scores.get("score", 100))
    cognitive_score = int(scores.get("cognitive", {}).get("score", 100))
    emotional_score = int(scores.get("emotional", {}).get("score", 100))

    if risk in config.ESCALATION_RISK_LEVELS:
        reasons.append(f"risk={risk}")
    if score < config.ESCALATION_SCORE_BELOW:
        reasons.append(f"overall_score={score}<{config.ESCALATION_SCORE_BELOW}")
    if cognitive_score < config.ESCALATION_SCORE_BELOW:
        reasons.append(
            f"cognitive_score={cognitive_score}<{config.ESCALATION_SCORE_BELOW}"
        )
    if emotional_score < config.ESCALATION_SCORE_BELOW:
        reasons.append(
            f"emotional_score={emotional_score}<{config.ESCALATION_SCORE_BELOW}"
        )

    return bool(reasons), reasons


def build_email(
    *,
    call_sid: str,
    scores: dict[str, Any],
    reasons: list[str],
    recipient: str,
) -> EmailMessage:
    """Build a bilingual caregiver alert email."""
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = config.EMAIL_FROM or config.SMTP_USERNAME
    message["Subject"] = f"MimaMori alert / 見守りアラート: {scores.get('risk')} risk"

    cognitive = scores.get("cognitive", {})
    emotional = scores.get("emotional", {})
    review_url = f"{config.DASHBOARD_BASE_URL.rstrip('/')}/calls/{call_sid}"

    english = f"""A MimaMori check-in call needs caregiver review.

Call ID: {call_sid}
Risk: {scores.get("risk")}
Overall score: {scores.get("score")}
Cognitive score: {cognitive.get("score")}
Emotional score: {emotional.get("score")}
Escalation reason: {", ".join(reasons)}

Cognitive note:
{cognitive.get("notes", "")}

Emotional note:
{emotional.get("notes", "")}

Review the call:
{review_url}
"""

    japanese = f"""MimaMoriの見守り通話で、介護者による確認が必要な可能性があります。

通話ID: {call_sid}
リスク: {scores.get("risk")}
総合スコア: {scores.get("score")}
認知スコア: {cognitive.get("score")}
感情スコア: {emotional.get("score")}
エスカレーション理由: {", ".join(reasons)}

認知面のメモ:
{cognitive.get("notes", "")}

感情面のメモ:
{emotional.get("notes", "")}

通話を確認:
{review_url}
"""

    message.set_content(f"{english}\n---\n\n{japanese}")
    return message


def send_email(message: EmailMessage) -> None:
    """Send an email using the configured SMTP server."""
    if not config.SMTP_HOST:
        raise RuntimeError("SMTP_HOST is required to send escalation email.")
    if not message.get("From"):
        raise RuntimeError("EMAIL_FROM or SMTP_USERNAME is required.")

    if config.SMTP_USE_TLS:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            if config.SMTP_USERNAME or config.SMTP_PASSWORD:
                smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            smtp.send_message(message)
    else:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            if config.SMTP_USERNAME or config.SMTP_PASSWORD:
                smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            smtp.send_message(message)


async def maybe_escalate_call(path: str, scores: dict[str, Any]) -> dict[str, Any]:
    """Send a caregiver alert when a scored transcript crosses thresholds.

    The transcript file is updated with an ``escalation`` block regardless of
    whether a notification is sent, skipped, or failed.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    existing = data.get("escalation")
    if existing and existing.get("status") == "sent":
        return existing

    call_sid = data.get("call_sid") or "unknown"
    now = datetime.now(timezone.utc).isoformat()

    if not config.ESCALATION_ENABLED:
        escalation = {
            "triggered": False,
            "status": "disabled",
            "checked_at": now,
        }
        _write_escalation(path, data, escalation)
        return escalation

    triggered, reasons = should_escalate(scores)
    if not triggered:
        escalation = {
            "triggered": False,
            "status": "not_required",
            "checked_at": now,
        }
        _write_escalation(path, data, escalation)
        return escalation

    if not config.CAREGIVER_EMAIL:
        escalation = {
            "triggered": True,
            "status": "failed",
            "recipient": None,
            "reasons": reasons,
            "checked_at": now,
            "error": "CAREGIVER_EMAIL is required.",
        }
        _write_escalation(path, data, escalation)
        logger.error("Escalation for %s failed: missing caregiver email", call_sid)
        return escalation

    message = build_email(
        call_sid=call_sid,
        scores=scores,
        reasons=reasons,
        recipient=config.CAREGIVER_EMAIL,
    )
    escalation = {
        "triggered": True,
        "status": "pending",
        "recipient": config.CAREGIVER_EMAIL,
        "reasons": reasons,
        "checked_at": now,
    }
    _write_escalation(path, data, escalation)

    try:
        await asyncio.to_thread(send_email, message)
    except Exception as exc:  # noqa: BLE001 - preserve call teardown/result flow
        escalation.update(
            {
                "status": "failed",
                "error": str(exc),
                "failed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_escalation(path, data, escalation)
        logger.exception("Escalation email for %s failed", call_sid)
        return escalation

    escalation.update(
        {
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _write_escalation(path, data, escalation)
    logger.info("Escalation email sent for %s to %s", call_sid, config.CAREGIVER_EMAIL)
    return escalation


def _write_escalation(path: str, data: dict[str, Any], escalation: dict[str, Any]) -> None:
    """Persist escalation status back into the transcript JSON."""
    data["escalation"] = escalation
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
