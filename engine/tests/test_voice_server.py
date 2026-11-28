"""Tests for the ElevenLabs custom-LLM voice server (no network, fake OpenAI client)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))
os.environ["VOICE_SERVER_NO_AUTOLOAD"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from llm_client import ChatActorClient  # noqa: E402
from voice_server import PatientSession, create_app  # noqa: E402

CASE = ENGINE_DIR / "data" / "mock_gerhard_mueller.json"


@pytest.fixture(autouse=True)
def _no_engine_key(monkeypatch):
    # load_dotenv() may pick up a developer's .env (it never overrides an existing
    # variable), so pin an empty key: tests start without auth.
    monkeypatch.setenv("ENGINE_API_KEY", "")


class FakeCompletions:
    def __init__(self, pieces: list[str]):
        self.pieces = pieces
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["stream"] is True
        return iter(
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=p))]) for p in self.pieces
        )


def make_client(pieces=("Well... ", "it's my chest.")):
    completions = FakeCompletions(list(pieces))
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    session = PatientSession(client_factory=lambda prompt: ChatActorClient(prompt, client=fake, model="test-model"))
    session.load(CASE)
    return TestClient(create_app(session, load_case=False)), completions


def history():
    return [
        {"role": "system", "content": "ElevenLabs system prompt that must be ignored"},
        {"role": "user", "content": "Hello, what brings you in today?"},
    ]


def test_streaming_sse_format_and_system_prompt():
    client, completions = make_client()
    r = client.post("/v1/chat/completions", json={"model": "x", "stream": True, "messages": history()})
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(l[6:]) for l in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "Well... it's my chest."
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    sent = completions.calls[0]["messages"]
    assert sent[0]["role"] == "system" and "ElevenLabs system prompt" not in sent[0]["content"]
    assert [m["role"] for m in sent] == ["system", "user"]


def test_non_streaming():
    client, _ = make_client()
    r = client.post("/v1/chat/completions", json={"messages": history()})
    assert r.json()["choices"][0]["message"]["content"] == "Well... it's my chest."


def test_auth_and_tunnel_guard(monkeypatch):
    client, _ = make_client()
    monkeypatch.setenv("ENGINE_API_KEY", "secret")
    assert client.post("/v1/chat/completions", json={"messages": history()}).status_code == 401
    ok = client.post("/v1/chat/completions", json={"messages": history()}, headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200
    # Through the tunnel only the public routes are reachable.
    assert client.get("/prompt", headers={"cf-ray": "x"}).status_code == 403
    assert client.get("/health", headers={"cf-ray": "x"}).status_code == 200
    assert client.get("/prompt").status_code == 200


@pytest.mark.parametrize("pieces", [()])
def test_empty_reply_is_not_a_crash(pieces):
    client, _ = make_client(pieces)
    r = client.post("/v1/chat/completions", json={"stream": True, "messages": history()})
    assert r.status_code == 200 and r.text.rstrip().endswith("data: [DONE]")


def test_load_teacher_case_and_list(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_test")
    client, completions = make_client()
    listed = client.get("/cases").json()
    assert any(c["case_id"] == "case-001" for c in listed["cases"])

    r = client.post("/case", json={"case_id": "case-001"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Martin Keller"
    assert r.json()["talk_url"].endswith("agent_id=agent_test")
    assert client.get("/health").json()["case_id"] == "case-001"

    client.post("/v1/chat/completions", json={"messages": history()})
    assert "Martin Keller" in completions.calls[-1]["messages"][0]["content"]

    assert client.post("/case", json={"case_id": "nope"}).status_code == 404
    # Loading cases is local only, never through the public tunnel.
    assert client.post("/case", json={"case_id": "case-001"}, headers={"cf-ray": "x"}).status_code == 403


def test_stage_relays_audio_and_emotion_to_unreal():
    client, _ = make_client()
    with client.websocket_connect("/ws/unreal") as unreal:
        assert json.loads(unreal.receive_text()) == {"type": "emotion", "emotion": "neutral", "intensity": 0.6}
        with client.websocket_connect("/ws/stage") as stage:
            assert json.loads(stage.receive_text()) == {"type": "status", "unreal": 1}
            stage.send_text(json.dumps({"type": "audio", "sample_rate": 16000, "pcm_b64": "AAABAA=="}))
            assert json.loads(unreal.receive_text()) == {"type": "audio", "sample_rate": 16000, "pcm_b64": "AAABAA=="}
            stage.send_text(json.dumps({"type": "emotion", "emotion": "furious", "intensity": 3}))
            assert json.loads(unreal.receive_text()) == {"type": "emotion", "emotion": "neutral", "intensity": 1.0}
        # Loading a teacher case sends its mood (case-001: neutral; set a different one inline).
        case = json.loads((ENGINE_DIR.parent / "cases" / "case-001.json").read_text(encoding="utf-8"))
        case["personality"]["mood"] = "sad"
        assert client.post("/case", json={"case": case}).json()["mood"] == "sad"
        assert json.loads(unreal.receive_text())["emotion"] == "sad"


def test_websockets_closed_through_tunnel():
    from starlette.websockets import WebSocketDisconnect

    client, _ = make_client()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/unreal", headers={"cf-ray": "x"}) as ws:
            ws.receive_text()
