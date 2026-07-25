# MimaMori — Outbound Caller

Twilio Media Streams ↔ OpenAI Realtime API bridge for the daily eldercare
check-in call. Adapted from Twilio's
[outbound-calls-python-openai-realtime-api](https://www.twilio.com/en-us/blog/outbound-calls-python-openai-realtime-api-voice)
tutorial.

## What it does

1. Places an outbound call to the elderly person (`POST /outbound-call` or the
   `--call` CLI).
2. When answered, Twilio streams the call audio to `wss://<DOMAIN>/media-stream`.
3. That WebSocket proxies audio to the OpenAI Realtime API, which holds a warm
   Japanese conversation (persona in `persona.py`) and speaks first.
4. Every utterance on both sides is captured and saved to
   `../data/transcripts/<timestamp>_<callSid>.json` for the scoring pipeline.
5. When Twilio finishes processing the call recording, it calls
   `POST /recording-status`; the server downloads the MP3 to
   `../data/recordings/<timestamp>_<callSid>_<recordingSid>.mp3`.

## Setup

1. Fill in `backend/.env` (see `.env.example`). You still need:
   - `TWILIO_ACCOUNT_SID` — your **AC...** account SID (the `SK...` value already
     present is an API *key*, kept in `TWILIO_API_KEY_SID`).
   - `PHONE_NUMBER_FROM` — a Twilio number you own, E.164 format.
   - `DOMAIN` — your ngrok domain (next step).
2. Expose the local port so Twilio can reach it:
   ```bash
   ngrok http 6060
   ```
   Copy the forwarding host (no `https://`) into `DOMAIN` in `.env`.
3. Make sure the destination number is a **verified caller ID** in the Twilio
   console (trial accounts can only call verified numbers).

## Run

Server (what the daily cron calls):
```bash
uv run uvicorn mimamori.main:app --port 6060
# then trigger a call:
curl -X POST localhost:6060/outbound-call -H 'content-type: application/json' \
     -d '{"to": "+81XXXXXXXXXX"}'
```

One-shot demo (places the call, then serves the stream — matches the tutorial):
```bash
uv run python -m mimamori.main --call=+81XXXXXXXXXX
```

## Tests

```bash
uv run pytest        # smoke tests, no network / no real calls
```

## Compliance

Outbound AI calls are subject to **TCPA** and local law. Only call numbers you
own or have explicit consent to call. `check_number_allowed()` restricts calls
to Twilio-owned or verified numbers as a guardrail.
