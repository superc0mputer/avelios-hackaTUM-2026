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
        assert json.loads(unreal.receive_text()) == {"type": "viewers", "count": 0}
        with client.websocket_connect("/ws/stage") as stage:
            assert json.loads(stage.receive_text()) == {"type": "status", "unreal": 1}
            stage.send_text(json.dumps({"type": "audio", "sample_rate": 16000, "pcm_b64": "AAABAA=="}))
            assert json.loads(unreal.receive_text()) == {"type": "audio", "sample_rate": 16000, "pcm_b64": "AAABAA==", "audible": True}
            # A tester elsewhere: the lips move, but the demo computer stays quiet
            stage.send_text(json.dumps({"type": "audio", "pcm_b64": "AAABAA==", "audible": False}))
            assert json.loads(unreal.receive_text())["audible"] is False
            stage.send_text(json.dumps({"type": "emotion", "emotion": "furious", "intensity": 3}))
            assert json.loads(unreal.receive_text()) == {"type": "emotion", "emotion": "neutral", "intensity": 1.0}
            stage.send_text(json.dumps({"type": "state", "state": "listening"}))
            assert json.loads(unreal.receive_text()) == {"type": "state", "state": "listening"}
        # Loading a teacher case sends who the patient is, then the mood (case-001: neutral; set one inline).
        case = json.loads((ENGINE_DIR.parent / "cases" / "case-001.json").read_text(encoding="utf-8"))
        case["personality"]["mood"] = "sad"
        assert client.post("/case", json={"case": case}).json()["mood"] == "sad"
        look = json.loads(unreal.receive_text())
        assert look["type"] == "case"
        assert look["case"]["character_id"] == "man-01" and look["case"]["patient"]["age"] == 58
        # Unreal gets the look only: never the diagnosis, the facts or the secrets
        assert "diagnosis" not in look["case"] and "secrets" not in look["case"]
        assert "life_story" not in look["case"]["patient"]
        assert json.loads(unreal.receive_text())["emotion"] == "sad"
        # A student turn makes the patient think until the voice arrives
        client.post("/v1/chat/completions", json={"messages": history()})
        assert json.loads(unreal.receive_text()) == {"type": "state", "state": "thinking"}

    # A patient window that connects later still gets the loaded case first
    with client.websocket_connect("/ws/unreal") as late:
        assert json.loads(late.receive_text())["type"] == "case"
        assert json.loads(late.receive_text())["type"] == "emotion"


def test_websockets_closed_through_tunnel():
    from starlette.websockets import WebSocketDisconnect

    client, _ = make_client()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/unreal", headers={"cf-ray": "x"}) as ws:
            ws.receive_text()


def test_video_frames_reach_viewers_and_unreal_knows_who_watches():
    client, _ = make_client()
    with client.websocket_connect("/ws/unreal") as unreal:
        assert json.loads(unreal.receive_text())["type"] == "emotion"
        assert json.loads(unreal.receive_text()) == {"type": "viewers", "count": 0}
        with client.websocket_connect("/ws/video") as viewer:
            assert json.loads(unreal.receive_text()) == {"type": "viewers", "count": 1}
            unreal.send_bytes(b"\xff\xd8jpeg-1")
            assert viewer.receive_bytes() == b"\xff\xd8jpeg-1"
        # Nobody watches any more: Unreal can stop capturing
        assert json.loads(unreal.receive_text()) == {"type": "viewers", "count": 0}


def test_public_access_code(monkeypatch):
    import httpx

    from voice_server import ACCESS_COOKIE, access_token

    client, _ = make_client()
    client.app.state.teacher_transport = httpx.MockTransport(lambda req: httpx.Response(200, text="teacher " + req.url.path))
    tunnel = {"cf-ray": "x"}
    # Without PUBLIC_ACCESS_CODE the tunnel serves ElevenLabs only
    monkeypatch.delenv("PUBLIC_ACCESS_CODE", raising=False)
    assert client.get("/", headers=tunnel, follow_redirects=False).status_code == 403

    monkeypatch.setenv("PUBLIC_ACCESS_CODE", "letmein")
    first = client.get("/", headers=tunnel, follow_redirects=False)
    assert first.status_code == 303 and first.headers["location"] == "/access"
    assert client.post("/access", content="code=wrong", headers=tunnel).status_code == 401
    ok = client.post("/access", content="code=letmein", headers=tunnel, follow_redirects=False)
    assert ok.status_code == 303 and "letmein" not in ok.headers["set-cookie"]

    allowed = {**tunnel, "cookie": f"{ACCESS_COOKIE}={access_token('letmein')}"}
    page = client.get("/app.js", headers=allowed)
    assert page.status_code == 200 and page.text == "teacher /app.js"
    # The prompt holds the case's secrets: never public, not even with the code
    assert client.get("/prompt", headers=allowed).status_code == 403
    assert client.post("/case", json={"case_id": "case-001"}, headers=allowed).status_code == 403

    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/video", headers=tunnel) as ws:
            ws.receive_bytes()
    with client.websocket_connect("/ws/video", headers=allowed) as ws:
        pass  # accepted with the code
