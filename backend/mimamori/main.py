"""MimaMori outbound-call server: Twilio Media Streams <-> OpenAI Realtime API.

Adapted from Twilio's "outbound calls with Python + OpenAI Realtime API"
tutorial for the MimaMori daily eldercare check-in. Differences from the vanilla
tutorial:

- Japanese warm-companion persona (see ``persona.py``).
- Transcript capture: every utterance on both sides is saved to
  ``data/transcripts/`` for the downstream scoring pipeline.
- A ``POST /outbound-call`` endpoint so the daily cron can place a call without
  restarting the process (the ``--call`` CLI is kept for one-shot demos).
- A ``POST /check-in`` endpoint that places the call and returns immediately
  (202); the transcript is scored automatically when the call ends, and results
  are fetched from ``GET /result/{call_sid}``.

Audio note: Twilio Media Streams use G.711 mu-law @ 8kHz, so the OpenAI session
declares ``g711_ulaw`` for both input and output — mismatched formats are the
most common cause of static/silence.

Run the server:      uv run uvicorn mimamori.main:app --port 6060
One-shot demo call:  uv run python -m mimamori.main --call=+81XXXXXXXXXX
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import uvicorn
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, field_validator
from twilio.rest import Client

from . import calls, config
from .escalation import maybe_escalate_call
from .persona import INITIAL_GREETING, SYSTEM_MESSAGE
from .recording import download_recording
from .score.pipeline import score_transcript_file
from .transcript import CallTranscript, find_transcript

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mimamori")

# Assistant audio deltas — GA renamed the beta event, so accept both.
AUDIO_DELTA_EVENTS = {"response.output_audio.delta", "response.audio.delta"}
# Assistant spoken-transcript "done" — likewise beta + GA names.
ASSISTANT_TRANSCRIPT_EVENTS = {
    "response.output_audio_transcript.done",
    "response.audio_transcript.done",
}

# Realtime API events worth logging while developing.
LOG_EVENT_TYPES = {
    "error",
    "response.created",
    "response.done",
    "session.created",
    "session.updated",
    "input_audio_buffer.speech_started",
    "conversation.item.input_audio_transcription.completed",
}

app = FastAPI(title="MimaMori Outbound Caller")

# Allow the Next.js dashboard (localhost:3000 in dev) to call this API from the
# browser. Origins are configurable via CORS_ORIGINS (comma-separated).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CallRequest(BaseModel):
    """Browser/API request to place an outbound call."""

    to: str

    @field_validator("to")
    @classmethod
    def require_to_number(cls, value: str) -> str:
        """Reject empty destination numbers before reaching Twilio."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("'to' phone number is required.")
        return stripped


class ScheduleCallRequest(CallRequest):
    """Browser/API request to place a daily scheduled outbound call."""

    call_time: str

    @field_validator("call_time")
    @classmethod
    def require_hhmm_time(cls, value: str) -> str:
        """Accept only a local HH:MM schedule time."""
        stripped = value.strip()
        parts = stripped.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("'call_time' must be in HH:MM format.")
        hour, minute = (int(part) for part in parts)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("'call_time' must be a valid 24-hour time.")
        return f"{hour:02d}:{minute:02d}"


ScheduledCallStatus = Literal["scheduled", "calling", "complete", "failed"]
SCHEDULE_TIMEZONE = ZoneInfo("Asia/Tokyo")


class ScheduledCall(BaseModel):
    """In-memory demo schedule record."""

    schedule_id: str
    to: str
    call_time: str
    timezone: str = "Asia/Tokyo"
    next_run_at: datetime
    status: ScheduledCallStatus = "scheduled"
    last_call_sid: str | None = None
    error: str | None = None


# Demo-only in-process scheduler state. TODO: replace with durable storage and a
# real recurring scheduler before production use.
_scheduled_calls: dict[str, ScheduledCall] = {}
_scheduled_tasks: dict[str, asyncio.Task[None]] = {}


def _twilio_client() -> Client:
    """Build a Twilio client, failing clearly if credentials are missing."""
    return Client(*config.twilio_client_args())


def _outbound_twiml() -> str:
    """TwiML that connects the answered call to our media-stream WebSocket."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="wss://{config.DOMAIN}/media-stream" />'
        "</Connect>"
        "</Response>"
    )


def _recording_status_callback_url() -> str:
    """URL Twilio calls when the call recording is available."""
    return f"https://{config.DOMAIN}/recording-status"


async def check_number_allowed(client: Client, to: str) -> bool:
    """Check that ``to`` is a number we're permitted to call.

    Guards against dialing arbitrary numbers. A destination is allowed if it is
    on the explicit ``ALLOWED_DESTINATIONS`` allowlist (the primary mechanism on
    a Full account), OR is a Twilio-owned number, OR is a verified caller ID
    (the trial-account path). Only call numbers you have explicit consent to
    call — TCPA applies to AI-placed calls too.

    Args:
        client: Authenticated Twilio client.
        to: Destination number in E.164 format.

    Returns:
        True if the number may be called.
    """
    if to in config.ALLOWED_DESTINATIONS:
        return True
    try:
        incoming = client.incoming_phone_numbers.list(phone_number=to)
        if incoming:
            return True
        outgoing = client.outgoing_caller_ids.list(phone_number=to)
        if outgoing:
            return True
    except Exception as exc:  # noqa: BLE001 - surface any Twilio API error clearly
        logger.error("Error checking allowed number %s: %s", to, exc)
    return False


async def make_call(to_number: str) -> str:
    """Validate a destination and place the outbound call.

    Args:
        to_number: Destination number in E.164 format (e.g. ``+8150...``).

    Returns:
        The created Twilio call SID.

    Raises:
        RuntimeError: If required config is missing or the number isn't allowed.
    """
    config.require("PHONE_NUMBER_FROM", "DOMAIN")
    client = _twilio_client()

    if not await check_number_allowed(client, to_number):
        raise RuntimeError(
            f"Number {to_number} is not allowed. Add it as a verified caller ID "
            "in the Twilio console (or use a number you own). TCPA applies to "
            "AI-placed calls."
        )

    call = client.calls.create(
        from_=config.PHONE_NUMBER_FROM,
        to=to_number,
        twiml=_outbound_twiml(),
        # Twilio-side recording as a backup input for the scoring pipeline; the
        # Realtime transcript (captured below) is the primary source.
        record=True,
        recording_status_callback=_recording_status_callback_url(),
        recording_status_callback_event=["completed"],
    )
    logger.info("Placed call %s to %s", call.sid, to_number)
    return call.sid


def _next_daily_run_at(call_time: str, now: datetime | None = None) -> datetime:
    """Return the next UTC datetime for an Asia/Tokyo HH:MM daily call."""
    hour, minute = (int(part) for part in call_time.split(":"))
    local_now = (now or datetime.now(UTC)).astimezone(SCHEDULE_TIMEZONE)
    next_local = local_now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    if next_local <= local_now:
        next_local += timedelta(days=1)
    return next_local.astimezone(UTC)


async def _run_scheduled_call(schedule_id: str) -> None:
    """Run a scheduled call every day at its configured local time."""
    while schedule_id in _scheduled_calls:
        scheduled = _scheduled_calls[schedule_id]
        scheduled.next_run_at = _next_daily_run_at(scheduled.call_time)
        delay_seconds = max(
            0.0,
            (scheduled.next_run_at - datetime.now(UTC)).total_seconds(),
        )
        await asyncio.sleep(delay_seconds)

        scheduled.status = "calling"
        try:
            scheduled.last_call_sid = await make_call(scheduled.to)
            scheduled.error = None
        except Exception as exc:  # noqa: BLE001 - keep the demo schedule observable
            scheduled.status = "failed"
            scheduled.error = str(exc)
            logger.exception("Scheduled call %s failed", schedule_id)
        finally:
            if schedule_id in _scheduled_calls:
                scheduled.status = "scheduled"
                scheduled.next_run_at = _next_daily_run_at(scheduled.call_time)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/outbound-call")
async def outbound_call(body: CallRequest) -> JSONResponse:
    """Trigger a check-in call. Body: ``{"to": "+81XXXXXXXXXX"}``.

    This is what the daily 9:00 JST cron hits.
    """
    try:
        call_sid = await make_call(body.to)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"call_sid": call_sid, "to": body.to})


@app.post("/check-in")
async def check_in(body: CallRequest) -> JSONResponse:
    """Start a check-in call and return immediately (202).

    Body: ``{"to": "+81XXXXXXXXXX"}``. Places the call and returns a
    ``result_url``; the transcript is scored automatically when the call ends,
    so poll ``GET /result/{call_sid}`` for the outcome.
    """
    try:
        call_sid = await make_call(body.to)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(
        status_code=202,
        content={
            "call_sid": call_sid,
            "to": body.to,
            "status": "calling",
            "result_url": f"/result/{call_sid}",
        },
    )


@app.post("/schedule-call")
async def schedule_call(body: ScheduleCallRequest) -> JSONResponse:
    """Schedule a recurring daily check-in call.

    Body: ``{"to": "+81XXXXXXXXXX", "call_time": "09:00"}``. The time is
    interpreted in Asia/Tokyo, matching the care dashboard.
    This demo scheduler is in-process and will not survive server restarts.
    """
    schedule_id = f"schedule_{uuid.uuid4().hex}"
    scheduled = ScheduledCall(
        schedule_id=schedule_id,
        to=body.to,
        call_time=body.call_time,
        next_run_at=_next_daily_run_at(body.call_time),
    )
    _scheduled_calls[schedule_id] = scheduled
    _scheduled_tasks[schedule_id] = asyncio.create_task(_run_scheduled_call(schedule_id))
    return JSONResponse(status_code=202, content=scheduled.model_dump(mode="json"))


@app.get("/scheduled-calls/{schedule_id}")
async def get_scheduled_call(schedule_id: str) -> JSONResponse:
    """Return the current state of a scheduled call."""
    scheduled = _scheduled_calls.get(schedule_id)
    if not scheduled:
        raise HTTPException(status_code=404, detail=f"No scheduled call {schedule_id}.")
    return JSONResponse(scheduled.model_dump(mode="json"))


@app.get("/calls")
async def list_calls() -> JSONResponse:
    """List every scored call for the dashboard, newest first.

    Reshapes the scored transcript files into the frontend's call shape (score,
    risk, criteria, transcript turns, duration). Presentational/i18n fields stay
    hardcoded on the frontend and are merged there.
    """
    return JSONResponse(calls.list_calls())


@app.get("/calls/{call_sid}")
async def get_call(call_sid: str) -> JSONResponse:
    """Return one scored call by SID, or 404 if it hasn't been scored yet."""
    call = calls.get_call(call_sid)
    if not call:
        raise HTTPException(status_code=404, detail=f"No scored call {call_sid}.")
    return JSONResponse(call)


@app.get("/result/{call_sid}")
async def result(call_sid: str) -> JSONResponse:
    """Fetch a check-in's scores by call SID.

    Returns ``status: "pending"`` until the call ends and its transcript is
    written, then ``status: "complete"`` with the scores. Scores are normally
    computed at hang-up; if a transcript exists but wasn't scored, it is scored
    on demand here as a fallback.
    """
    path = find_transcript(call_sid)
    if not path:
        return JSONResponse({"call_sid": call_sid, "status": "pending"})

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    scores = data.get("scores") or await score_transcript_file(path)
    await maybe_escalate_call(path, scores)

    return JSONResponse(
        {
            "call_sid": call_sid,
            "status": "complete",
            "transcript": path,
            "scores": scores,
        }
    )


@app.post("/recording-status")
async def recording_status(request: Request) -> JSONResponse:
    """Persist the Twilio call recording once Twilio finishes processing it."""
    from urllib.parse import parse_qs

    body = (await request.body()).decode("utf-8")
    form = {key: values[-1] for key, values in parse_qs(body).items()}
    status = form.get("RecordingStatus")
    call_sid = form.get("CallSid")
    recording_sid = form.get("RecordingSid")

    if status != "completed":
        logger.warning(
            "Recording not downloaded for call %s: status=%s recording=%s",
            call_sid,
            status,
            recording_sid,
        )
        return JSONResponse({"saved": False, "status": status})

    if not call_sid or not recording_sid:
        raise HTTPException(
            status_code=400,
            detail="RecordingStatus callback missing CallSid or RecordingSid.",
        )

    try:
        path = await download_recording(call_sid=call_sid, recording_sid=recording_sid)
    except Exception as exc:  # noqa: BLE001 - Twilio should retry non-2xx callbacks
        logger.error("Failed to download recording %s: %s", recording_sid, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return JSONResponse({"saved": True, "path": path})


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket) -> None:
    """Bridge audio between a Twilio call and the OpenAI Realtime API."""
    await websocket.accept()
    logger.info("Twilio media stream connected")

    config.require("OPENAI_API_KEY")
    openai_url = f"wss://api.openai.com/v1/realtime?model={config.REALTIME_MODEL}"

    # websockets>=14 uses `additional_headers` (not `extra_headers`).
    # NOTE: The GA Realtime models (gpt-realtime*) reject the old beta shape.
    # Do NOT send `OpenAI-Beta: realtime=v1` — it triggers
    # `beta_api_shape_disabled`. Auth header alone is correct for GA.
    async with websockets.connect(
        openai_url,
        additional_headers={
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        },
    ) as openai_ws:
        await initialize_session(openai_ws)

        # Per-call state shared between the two pump coroutines below.
        state: dict[str, object] = {
            "stream_sid": None,
            "transcript": None,
            "assistant_response_active": False,
        }

        async def receive_from_twilio() -> None:
            """Forward caller audio (and stream lifecycle) to OpenAI."""
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    event = data.get("event")
                    if event == "media":
                        await openai_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": data["media"]["payload"],
                                }
                            )
                        )
                    elif event == "start":
                        start = data["start"]
                        state["stream_sid"] = start["streamSid"]
                        call_sid = start.get("callSid", start["streamSid"])
                        state["transcript"] = CallTranscript(call_sid=call_sid)
                        logger.info("Stream started: %s", state["stream_sid"])
                    elif event == "stop":
                        logger.info("Twilio stream stopped")
                        break
            except WebSocketDisconnect:
                logger.info("Twilio disconnected")
            finally:
                await openai_ws.close()

        async def send_to_twilio() -> None:
            """Forward OpenAI audio to Twilio and capture the transcript."""
            try:
                async for raw in openai_ws:
                    response = json.loads(raw)
                    rtype = response.get("type")

                    if rtype in LOG_EVENT_TYPES:
                        logger.info("OpenAI event: %s", rtype)

                    if rtype == "response.created":
                        state["assistant_response_active"] = True

                    if rtype == "response.done":
                        state["assistant_response_active"] = False

                    if rtype == "input_audio_buffer.speech_started":
                        await handle_caller_barge_in(openai_ws, websocket, state)

                    # Assistant audio -> Twilio. Accept beta + GA event names.
                    if rtype in AUDIO_DELTA_EVENTS and response.get("delta"):
                        await websocket.send_json(
                            {
                                "event": "media",
                                "streamSid": state["stream_sid"],
                                "media": {"payload": response["delta"]},
                            }
                        )

                    # Capture the elderly person's speech transcript.
                    if rtype == "conversation.item.input_audio_transcription.completed":
                        _record(state, "user", response.get("transcript", ""))

                    # Capture the assistant's spoken transcript (beta + GA names).
                    if rtype in ASSISTANT_TRANSCRIPT_EVENTS:
                        _record(state, "assistant", response.get("transcript", ""))
            except websockets.exceptions.ConnectionClosed:
                logger.info("OpenAI connection closed")
            finally:
                transcript = state.get("transcript")
                if isinstance(transcript, CallTranscript):
                    path = transcript.save()
                    # Score the completed call automatically so results are ready
                    # for GET /result. Never let scoring break stream teardown.
                    if path:
                        try:
                            scores = await score_transcript_file(path)
                            await maybe_escalate_call(path, scores)
                        except Exception:  # noqa: BLE001
                            logger.exception("Scoring or escalation failed for %s", path)

        await asyncio.gather(receive_from_twilio(), send_to_twilio())


def _record(state: dict[str, object], role: str, text: str) -> None:
    """Append a turn to the in-progress transcript, if one exists."""
    transcript = state.get("transcript")
    if isinstance(transcript, CallTranscript):
        transcript.add(role, text)


async def initialize_session(openai_ws) -> None:
    """Configure the Realtime session (GA shape) and prompt the AI first.

    GA differs from the beta tutorial: audio config is nested under
    ``audio.input`` / ``audio.output``, formats are objects (``audio/pcmu`` for
    Twilio's G.711 mu-law), and ``modalities`` became ``output_modalities``.
    """
    session_update = {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": SYSTEM_MESSAGE,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    # Twilio Media Streams are G.711 mu-law @ 8kHz.
                    "format": {"type": "audio/pcmu"},
                    "turn_detection": {
                        "type": "server_vad",
                        "interrupt_response": True,
                    },
                    # Transcribe the caller's speech so the pipeline can score it.
                    "transcription": {"model": "whisper-1"},
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": config.VOICE,
                },
            },
        },
    }
    await openai_ws.send(json.dumps(session_update))
    await send_initial_greeting(openai_ws)


async def handle_caller_barge_in(
    openai_ws, websocket: WebSocket, state: dict[str, object]
) -> None:
    """Stop assistant audio playback as soon as the caller starts speaking."""
    if state.get("assistant_response_active"):
        await openai_ws.send(json.dumps({"type": "response.cancel"}))

    stream_sid = state.get("stream_sid")
    if isinstance(stream_sid, str):
        await websocket.send_json({"event": "clear", "streamSid": stream_sid})


async def send_initial_greeting(openai_ws) -> None:
    """Make the AI greet first — the caller has just answered the phone."""
    await openai_ws.send(
        json.dumps(
            {
                "type": "response.create",
                "response": {
                    "instructions": INITIAL_GREETING,
                    "output_modalities": ["audio"],
                },
            }
        )
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Human-friendly status page."""
    return "<h1>MimaMori outbound caller is running.</h1>"


def _cli() -> None:
    """Command-line entrypoint: place one call, then serve the media stream."""
    parser = argparse.ArgumentParser(description="MimaMori outbound caller")
    parser.add_argument(
        "--call",
        required=True,
        help="Destination phone number in E.164 format, e.g. +81501234567",
    )
    args = parser.parse_args()

    print(
        "\n" + "=" * 68,
        "\nReminder: outbound AI calls are subject to TCPA and local law.",
        "\nOnly call numbers you own or have explicit consent to call.\n",
        "=" * 68 + "\n",
    )

    async def _startup() -> None:
        await make_call(args.call)

    # Place the call, then run the server so the media stream can connect.
    asyncio.get_event_loop().run_until_complete(_startup())
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)


if __name__ == "__main__":
    _cli()
