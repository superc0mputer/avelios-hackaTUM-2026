"""The packaged app's key routes on the voice server (no network: checks and ElevenLabs are faked)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))
os.environ["VOICE_SERVER_NO_AUTOLOAD"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

import voice_server  # noqa: E402
from llm_client import ChatActorClient  # noqa: E402

CASE = ENGINE_DIR / "data" / "mock_gerhard_mueller.json"


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIP_KEYSTORE_PATH", str(tmp_path / "keys.bin"))
    monkeypatch.setattr(voice_server, "APP_MODE", True)
    for name in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ENGINE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATIENT_CASE_PATH", str(CASE))

    calls = {"ensure": [], "prompt": []}
    monkeypatch.setattr(voice_server.key_check, "check_openai", lambda k, m=None: {"ok": k.startswith("sk-")} | ({} if k.startswith("sk-") else {"error": "bad openai"}))
    monkeypatch.setattr(voice_server.key_check, "check_elevenlabs", lambda k: {"ok": True, "credits_left": 9000})

    def ensure(el, oa, model, agent_id=None):
        calls["ensure"].append((el, oa, agent_id))
        return agent_id or "agent_new"

    monkeypatch.setattr(voice_server.eleven_agent, "ensure_agent", ensure)
    monkeypatch.setattr(voice_server.eleven_agent, "set_prompt", lambda k, a, p: calls["prompt"].append((a, p)))
    monkeypatch.setattr(voice_server.eleven_agent, "signed_url", lambda k, a: f"wss://signed/{a}")

    fake = SimpleNamespace(chat=SimpleNamespace(completions=None))
    session = voice_server.PatientSession(client_factory=lambda prompt: ChatActorClient(prompt, client=fake, model="m"))
    # create_app tolerates the missing key in app mode only because the real client would fail;
    # here we start without a loaded case and let the key screen load it.
    app = voice_server.create_app(session, load_case=False)
    session.source = CASE
    return TestClient(app), calls


def test_first_start_reports_missing_keys(app_env):
    client, _ = app_env
    assert client.get("/keys").json() == {
        "app": True, "openai": False, "elevenlabs": False, "agent": False, "model": os.getenv("OPENAI_MODEL") or "gpt-6-luna",
        "ready": False,
    }


def test_saving_keys_sets_up_agent_and_loads_case(app_env):
    client, calls = app_env
    result = client.post("/keys", json={"openai_key": "sk-judge", "elevenlabs_key": "el-judge"}).json()
    assert result["ready"] and result["agent"] and result["elevenlabs"]
    assert calls["ensure"] == [("el-judge", "sk-judge", None)]
    assert calls["prompt"] and calls["prompt"][0][0] == "agent_new"
    assert "voice_error" not in result
    # stored for the next start, values never echoed back
    assert "sk-judge" not in str(result)
    assert voice_server.keystore.load()["ELEVENLABS_AGENT_ID"] == "agent_new"
    assert client.get("/signed-url").json() == {"signed_url": "wss://signed/agent_new"}


def test_bad_key_stores_nothing(app_env):
    client, calls = app_env
    response = client.post("/keys", json={"openai_key": "wrong", "elevenlabs_key": "el-judge"})
    assert response.status_code == 422
    assert response.json()["detail"]["errors"] == {"openai": "bad openai"}
    assert voice_server.keystore.load() == {} and calls["ensure"] == []


def test_forget_keys(app_env):
    client, _ = app_env
    client.post("/keys", json={"openai_key": "sk-judge", "elevenlabs_key": "el-judge"})
    assert client.delete("/keys").json()["ready"] is False
    assert voice_server.keystore.load() == {}
    assert client.get("/signed-url").status_code == 409


def test_case_load_pushes_prompt_to_agent(app_env):
    client, calls = app_env
    client.post("/keys", json={"openai_key": "sk-judge", "elevenlabs_key": "el-judge"})
    calls["prompt"].clear()
    result = client.post("/case", json={"case_id": CASE.stem}).json()
    assert result["signed"] is True and result["talk_url"] is None
    assert len(calls["prompt"]) == 1
