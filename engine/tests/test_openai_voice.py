"""Tests for the OpenAI voice route (/ws/talk), with fake OpenAI clients (no network)."""

from __future__ import annotations

import base64
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

import openai_voice  # noqa: E402
from llm_client import ChatActorClient  # noqa: E402
from openai_voice import choose_voice, language_code, split_sentences, voice_instructions  # noqa: E402
from voice_server import PatientSession, create_app  # noqa: E402

CASE = ENGINE_DIR / "data" / "mock_gerhard_mueller.json"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ENGINE_API_KEY", "")
    monkeypatch.setenv("OPENAI_TTS_VOICE", "")
    # Keep the tests fast: no wait for the (fake) audio to "play".
    monkeypatch.setattr(openai_voice, "CHUNK_BYTES", 8)


class FakeVoice:
    def __init__(self, transcript="Hello, what brings you in?"):
        self.transcript = transcript
        self.wavs: list[bytes] = []
        self.spoken: list[tuple[str, str, str]] = []

    async def transcribe(self, wav, language=None):
        self.wavs.append(wav)
        return self.transcript

    async def speak(self, text, voice, instructions):
        self.spoken.append((text, voice, instructions))
        yield b"\x01\x00" * 6  # 12 bytes: one 8-byte chunk plus a 4-byte rest
        yield b"\x02\x00" * 2


class FakeCompletions:
    def __init__(self, pieces):
        self.pieces = pieces
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=p))]) for p in self.pieces)


def make_client(pieces=("Well, doctor, it started last night. ", "It's my chest, it feels tight."), voice=None):
    completions = FakeCompletions(list(pieces))
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    session = PatientSession(client_factory=lambda prompt: ChatActorClient(prompt, client=fake, model="test-model"))
    session.load(CASE)
    voice = voice or FakeVoice()
    return TestClient(create_app(session, load_case=False, voice=voice)), completions, voice


def utterance():
    return json.dumps({"type": "utterance", "sample_rate": 16000, "pcm_b64": base64.b64encode(b"\x00\x00" * 160).decode()})


def receive_until(ws, kind, state=None):
    seen = []
    while True:
        message = json.loads(ws.receive_text())
        seen.append(message)
        if message["type"] == kind and (state is None or message.get("state") == state):
            return seen


def test_split_sentences():
    ready, rest = split_sentences("Yes. It hurts here, doctor, when I walk. And then")
    assert ready == ["Yes. It hurts here, doctor, when I walk."] and rest == "And then"
    assert split_sentences("Short. ", final=True) == (["Short."], "")
    assert split_sentences("no end yet") == ([], "no end yet")


def test_language_code():
    assert language_code("English") == "en" and language_code("de-DE") == "de"
    assert language_code("Klingon") is None and language_code(None) is None


def test_voice_follows_the_case(monkeypatch):
    session = PatientSession(client_factory=lambda prompt: SimpleNamespace(model="m", system_prompt=prompt))
    session.load(CASE)
    config = session.config
    assert choose_voice(config) in ("ash", "coral", "sage")
    text = voice_instructions(config, "sad")
    assert config.demographics.full_name in text and str(config.demographics.age) in text
    assert "low, tired" in text
    monkeypatch.setenv("OPENAI_TTS_VOICE", "verse")
    assert choose_voice(config) == "verse"


def test_talk_without_unreal_plays_audio_in_the_page():
    client, completions, voice = make_client()
    with client.websocket_connect("/ws/talk") as ws:
        assert json.loads(ws.receive_text()) == {"type": "ready", "unreal": 0}
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "listening"}
        ws.send_text(utterance())
        seen = receive_until(ws, "state", "listening")
    kinds = [m["type"] for m in seen]
    assert seen[0] == {"type": "state", "state": "thinking"}
    assert {"type": "student", "text": "Hello, what brings you in?"} in seen
    assert kinds.count("audio") == 4  # per sentence 16 bytes: two 8-byte chunks
    assert all(m["sample_rate"] == 24000 for m in seen if m["type"] == "audio")
    patient = [m["text"] for m in seen if m["type"] == "patient"]
    assert patient[-1] == "Well, doctor, it started last night. It's my chest, it feels tight."
    assert voice.wavs[0][:4] == b"RIFF"
    # The engine got the transcript as the student's turn, behind its own system prompt.
    sent = completions.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"] and sent[1]["content"] == "Hello, what brings you in?"


def test_talk_with_unreal_sends_audio_and_states_to_the_metahuman():
    client, _, _ = make_client()
    with client.websocket_connect("/ws/unreal") as unreal:
        json.loads(unreal.receive_text())  # starting emotion
        with client.websocket_connect("/ws/talk") as ws:
            assert json.loads(ws.receive_text()) == {"type": "ready", "unreal": 1}
            assert json.loads(ws.receive_text()) == {"type": "state", "state": "listening"}
            ws.send_text(json.dumps({"type": "speech_start"}))
            ws.send_text(utterance())
            seen = receive_until(ws, "state", "listening")
            assert any(m["type"] == "patient" for m in seen)
            assert not any(m["type"] == "audio" for m in seen)
        to_unreal = []
        while True:
            message = json.loads(unreal.receive_text())
            to_unreal.append(message)
            if message == {"type": "state", "state": "idle"} and any(m["type"] == "audio" for m in to_unreal):
                break
    states = [m["state"] for m in to_unreal if m["type"] == "state"]
    assert states[:3] == ["listening", "listening", "thinking"]
    assert sum(m["type"] == "audio" for m in to_unreal) == 4


def test_second_conversation_turn_keeps_the_history():
    client, completions, _ = make_client(pieces=("Since yesterday evening, doctor.",))
    with client.websocket_connect("/ws/talk") as ws:
        receive_until(ws, "state", "listening")
        ws.send_text(utterance())
        receive_until(ws, "patient")
        receive_until(ws, "state", "listening")
        ws.send_text(utterance())
        receive_until(ws, "patient")
        receive_until(ws, "state", "listening")
    roles = [m["role"] for m in completions.calls[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
