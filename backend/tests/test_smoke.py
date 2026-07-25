"""Smoke tests: the module imports, config loads, TwiML/routes are well-formed.

These do not place real calls or hit any network. Run:  uv run pytest
"""

from __future__ import annotations

import json

import mimamori.config as config
from mimamori import main
from mimamori.recording import download_recording, recording_media_url
from mimamori.transcript import CallTranscript


def test_app_routes_present() -> None:
    paths = {r.path for r in main.app.routes if hasattr(r, "path")}
    assert "/health" in paths
    assert "/outbound-call" in paths
    assert "/recording-status" in paths
    assert "/media-stream" in paths
    assert "/calls" in paths
    assert "/schedule-call" in paths
    assert "/scheduled-calls/{schedule_id}" in paths


def test_list_calls_shapes_scored_transcript(tmp_path, monkeypatch) -> None:
    """A scored transcript is reshaped into the frontend's call shape."""
    from mimamori import calls

    monkeypatch.setattr(config, "TRANSCRIPT_DIR", str(tmp_path))
    transcript = {
        "call_sid": "CAtest",
        "started_at": "2026-07-24T09:00:00+00:00",
        "ended_at": "2026-07-24T09:04:30+00:00",
        "turns": [
            {"role": "assistant", "text": "おはよう", "at": "2026-07-24T09:00:05+00:00"},
            {"role": "user", "text": "眠れました", "at": "2026-07-24T09:00:20+00:00"},
        ],
        "scores": {
            "score": 82,
            "risk": "Low",
            "cognitive": {"score": 86, "criteria": {"repetition": 92}},
            "emotional": {"score": 78, "criteria": {"affect": 78}},
        },
    }
    (tmp_path / "20260724T090000Z_CAtest.json").write_text(
        json.dumps(transcript), encoding="utf-8"
    )

    (call,) = calls.list_calls()
    assert call["id"] == "CAtest"
    assert call["score"] == 82 and call["risk"] == "Low"
    # Duration derived from started/ended: 4m30s.
    assert (call["durationMinutes"], call["durationSeconds"]) == (4, 30)
    # Roles mapped to speakers; per-turn time is relative to call start.
    assert call["transcript"][0] == {
        "time": "00:05",
        "speaker": "MimaMori",
        "text": "おはよう",
    }
    assert call["transcript"][1]["speaker"] == "Recipient"


def test_list_calls_skips_unscored_transcript(tmp_path, monkeypatch) -> None:
    """A transcript without a scores block is omitted from the list."""
    from mimamori import calls

    monkeypatch.setattr(config, "TRANSCRIPT_DIR", str(tmp_path))
    (tmp_path / "20260724T090000Z_CAtest.json").write_text(
        json.dumps({"call_sid": "CAtest", "started_at": "", "turns": []}),
        encoding="utf-8",
    )
    assert calls.list_calls() == []


def test_escalation_sends_bilingual_email_once(tmp_path, monkeypatch) -> None:
    """A high-risk score sends one bilingual caregiver email and records status."""
    import asyncio

    from mimamori import escalation

    path = tmp_path / "20260724T090000Z_CAtest.json"
    scores = {
        "score": 58,
        "risk": "High",
        "cognitive": {"score": 62, "notes": "Memory concerns noted."},
        "emotional": {"score": 54, "notes": "Low mood noted."},
    }
    path.write_text(
        json.dumps({"call_sid": "CAtest", "turns": [], "scores": scores}),
        encoding="utf-8",
    )
    sent = []

    def fake_send_email(message) -> None:
        sent.append(message)

    monkeypatch.setattr(config, "ESCALATION_ENABLED", True)
    monkeypatch.setattr(config, "ESCALATION_SCORE_BELOW", 65)
    monkeypatch.setattr(config, "ESCALATION_RISK_LEVELS", {"High"})
    monkeypatch.setattr(config, "CAREGIVER_EMAIL", "jamieogundiran@gmail.com")
    monkeypatch.setattr(config, "EMAIL_FROM", "alerts@example.test")
    monkeypatch.setattr(config, "DASHBOARD_BASE_URL", "http://localhost:3000")
    monkeypatch.setattr(escalation, "send_email", fake_send_email)

    first = asyncio.run(escalation.maybe_escalate_call(str(path), scores))
    second = asyncio.run(escalation.maybe_escalate_call(str(path), scores))

    assert first["status"] == "sent"
    assert second["status"] == "sent"
    assert len(sent) == 1
    assert sent[0]["To"] == "jamieogundiran@gmail.com"
    body = sent[0].get_content()
    assert "A MimaMori check-in call needs caregiver review." in body
    assert "MimaMoriの見守り通話" in body
    assert "http://localhost:3000/calls/CAtest" in body

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["escalation"]["triggered"] is True
    assert data["escalation"]["status"] == "sent"


def test_escalation_skips_low_risk_score(tmp_path, monkeypatch) -> None:
    """Healthy calls are marked not_required and do not send email."""
    import asyncio

    from mimamori import escalation

    path = tmp_path / "20260724T090000Z_CAlow.json"
    scores = {
        "score": 90,
        "risk": "Low",
        "cognitive": {"score": 90},
        "emotional": {"score": 90},
    }
    path.write_text(
        json.dumps({"call_sid": "CAlow", "turns": [], "scores": scores}),
        encoding="utf-8",
    )

    def fail_send_email(message) -> None:
        raise AssertionError("low-risk calls should not send email")

    monkeypatch.setattr(config, "ESCALATION_ENABLED", True)
    monkeypatch.setattr(config, "ESCALATION_SCORE_BELOW", 65)
    monkeypatch.setattr(config, "ESCALATION_RISK_LEVELS", {"High"})
    monkeypatch.setattr(escalation, "send_email", fail_send_email)

    result = asyncio.run(escalation.maybe_escalate_call(str(path), scores))

    assert result["triggered"] is False
    assert result["status"] == "not_required"


def test_score_transcript_averages_three_model_ensemble(monkeypatch) -> None:
    """Scoring averages each criterion across the configured model ensemble."""
    import asyncio

    from mimamori.score import pipeline

    model_values = {
        "model-a": {"cognitive": 60, "emotional": 80},
        "model-b": {"cognitive": 66, "emotional": 82},
        "model-c": {"cognitive": 72, "emotional": 84},
    }

    class FakeGrader:
        def __init__(self, name: str, dimension: str) -> None:
            self.name = name
            self.dimension = dimension

        async def grade(self, item, *, model=None):
            assert "transcript" in item
            value = model_values[model][self.dimension]
            criteria = (
                pipeline.COGNITIVE_CRITERIA
                if self.dimension == "cognitive"
                else pipeline.EMOTIONAL_CRITERIA
            )
            return {
                "criteria": {key: value for key in criteria},
                "markers": ["coherence"] if self.dimension == "cognitive" else [],
                "notes": f"{model} {self.dimension} note",
            }

    monkeypatch.setattr(config, "AIAND_SCORING_MODELS", list(model_values))
    monkeypatch.setattr(config, "AIAND_SCORING_MIN_MODELS", 2)
    monkeypatch.setattr(
        pipeline,
        "COGNITIVE_GRADER",
        FakeGrader("fake cognitive", "cognitive"),
    )
    monkeypatch.setattr(
        pipeline,
        "EMOTIONAL_GRADER",
        FakeGrader("fake emotional", "emotional"),
    )

    scores = asyncio.run(
        pipeline.score_transcript(
            {
                "turns": [
                    {"role": "assistant", "text": "How are you?"},
                    {"role": "user", "text": "I feel okay."},
                ]
            }
        )
    )

    assert scores["model"] == "ensemble"
    assert scores["models"] == ["model-a", "model-b", "model-c"]
    assert scores["cognitive"]["score"] == 66
    assert scores["emotional"]["score"] == 82
    assert scores["score"] == 74
    assert scores["risk"] == "Watch"
    assert scores["cognitive"]["criteria"]["coherence"] == 66
    assert scores["model_scores"]["cognitive"]["model-a"]["score"] == 60
    assert scores["model_failures"] == {"cognitive": {}, "emotional": {}}


def test_outbound_twiml_wellformed(monkeypatch) -> None:
    monkeypatch.setattr(config, "DOMAIN", "example.ngrok-free.app")
    twiml = main._outbound_twiml()
    assert twiml.startswith("<?xml")
    assert 'wss://example.ngrok-free.app/media-stream' in twiml
    assert "<Connect>" in twiml and "<Stream" in twiml


def test_recording_status_callback_url(monkeypatch) -> None:
    monkeypatch.setattr(config, "DOMAIN", "example.ngrok-free.app")
    assert main._recording_status_callback_url() == (
        "https://example.ngrok-free.app/recording-status"
    )


def test_initial_greeting_is_assistant_response() -> None:
    import asyncio

    class FakeOpenAIWebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, payload: str) -> None:
            self.sent.append(payload)

    ws = FakeOpenAIWebSocket()
    asyncio.run(main.send_initial_greeting(ws))

    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["type"] == "response.create"
    assert payload["response"]["output_modalities"] == ["audio"]
    assert "instructions" in payload["response"]
    assert "item" not in payload


def test_barge_in_cancels_response_and_clears_twilio_buffer() -> None:
    import asyncio

    class FakeOpenAIWebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, payload: str) -> None:
            self.sent.append(payload)

    class FakeTwilioWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, str]] = []

        async def send_json(self, payload: dict[str, str]) -> None:
            self.sent.append(payload)

    openai_ws = FakeOpenAIWebSocket()
    twilio_ws = FakeTwilioWebSocket()
    state: dict[str, object] = {
        "stream_sid": "MZstream",
        "assistant_response_active": True,
    }

    asyncio.run(main.handle_caller_barge_in(openai_ws, twilio_ws, state))

    assert [json.loads(payload) for payload in openai_ws.sent] == [
        {"type": "response.cancel"}
    ]
    assert twilio_ws.sent == [{"event": "clear", "streamSid": "MZstream"}]


def test_transcript_capture_and_save(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "TRANSCRIPT_DIR", str(tmp_path))
    t = CallTranscript(call_sid="CAtest", to_number="+815012345678")
    t.add("assistant", "おはようございます")
    t.add("user", "  ")  # empty -> ignored
    t.add("user", "よく眠れました")
    assert len(t.turns) == 2
    path = t.save()
    assert path is not None and path.endswith(".json")


def test_transcript_empty_saves_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "TRANSCRIPT_DIR", str(tmp_path))
    assert CallTranscript(call_sid="CAempty").save() is None


def test_recording_media_url(monkeypatch) -> None:
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "AC" + "1" * 32)
    assert recording_media_url("RE" + "2" * 32).endswith(
        "/Accounts/AC11111111111111111111111111111111/"
        "Recordings/RE22222222222222222222222222222222.mp3"
    )


def test_recording_download_saves_mp3(tmp_path, monkeypatch) -> None:
    import asyncio

    import httpx

    monkeypatch.setattr(config, "RECORDING_DIR", str(tmp_path))
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "AC" + "1" * 32)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setattr(config, "TWILIO_API_KEY_SID", None)
    monkeypatch.setattr(config, "TWILIO_API_KEY_SECRET", None)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(
            "/Recordings/RE22222222222222222222222222222222.mp3"
        )
        return httpx.Response(200, content=b"mp3-bytes")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    path = asyncio.run(
        download_recording(
            call_sid="CA" + "3" * 32,
            recording_sid="RE" + "2" * 32,
            client=client,
        )
    )
    asyncio.run(client.aclose())

    assert path.endswith(".mp3")
    assert (tmp_path / path.split("/")[-1]).read_bytes() == b"mp3-bytes"


def test_recording_status_endpoint_downloads_completed(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    saved: dict[str, str] = {}

    async def fake_download_recording(*, call_sid: str, recording_sid: str) -> str:
        saved["call_sid"] = call_sid
        saved["recording_sid"] = recording_sid
        return "/tmp/call.mp3"

    monkeypatch.setattr(main, "download_recording", fake_download_recording)
    response = TestClient(main.app).post(
        "/recording-status",
        data={
            "RecordingStatus": "completed",
            "CallSid": "CA" + "3" * 32,
            "RecordingSid": "RE" + "2" * 32,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"saved": True, "path": "/tmp/call.mp3"}
    assert saved == {
        "call_sid": "CA" + "3" * 32,
        "recording_sid": "RE" + "2" * 32,
    }


def test_schedule_call_endpoint_registers_daily_schedule(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    async def fake_run_scheduled_call(schedule_id: str) -> None:
        assert schedule_id in main._scheduled_calls

    response = None
    monkeypatch.setattr(main, "_run_scheduled_call", fake_run_scheduled_call)
    try:
        response = TestClient(main.app).post(
            "/schedule-call",
            json={
                "to": "+819012345678",
                "call_time": "09:00",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["to"] == "+819012345678"
        assert data["status"] == "scheduled"
        assert data["call_time"] == "09:00"
        assert data["timezone"] == "Asia/Tokyo"
        assert data["next_run_at"]
        assert data["schedule_id"] in main._scheduled_calls
    finally:
        if response is not None and response.status_code == 202:
            schedule_id = response.json()["schedule_id"]
            task = main._scheduled_tasks.pop(schedule_id, None)
            if task is not None:
                task.cancel()
            main._scheduled_calls.pop(schedule_id, None)


def test_allowlisted_destination_permitted(monkeypatch) -> None:
    """A number on ALLOWED_DESTINATIONS is permitted without any Twilio lookup."""
    import asyncio

    monkeypatch.setattr(config, "ALLOWED_DESTINATIONS", {"+819012345678"})
    # client is unused for allowlisted numbers, so None is fine here.
    assert asyncio.run(main.check_number_allowed(None, "+819012345678")) is True


def test_twilio_args_api_key_style(monkeypatch) -> None:
    monkeypatch.setattr(config, "TWILIO_API_KEY_SID", "SKxxx")
    monkeypatch.setattr(config, "TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "ACyyy")
    assert config.twilio_client_args() == ("SKxxx", "secret", "ACyyy")
