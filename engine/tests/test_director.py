"""Tests for the per-turn face director (no network, fake OpenAI client)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from director import Director, case_floor, describe_case, parse_direction  # noqa: E402

CASE = json.loads((ENGINE_DIR.parent / "cases" / "case-001.json").read_text(encoding="utf-8"))


def test_parse_clamps_and_falls_back():
    d = parse_direction('{"emotion": "Fear", "intensity": 5, "pain": 12, "discomfort": -1}')
    assert d == {"type": "emotion", "emotion": "fear", "intensity": 2.0, "pain": 10.0, "discomfort": 0.0}
    assert parse_direction('{"emotion": "rage"}')["emotion"] == "neutral"
    assert parse_direction("not json") is None
    assert parse_direction("[1, 2]") is None


def test_case_pain_and_discomfort_are_the_floor():
    case = {**CASE, "presentation": {"pain": 4, "discomfort": 0.3}}
    assert case_floor(case) == {"pain": 4.0, "discomfort": 0.3}
    d = parse_direction('{"emotion": "neutral", "intensity": 0.4, "pain": 1, "discomfort": 0}', case_floor(case))
    assert d["pain"] == 4.0 and d["discomfort"] == 0.3


def test_describe_case_has_what_the_face_needs():
    text = describe_case({**CASE, "presentation": {"pain": 4}})
    assert "Martin Keller" in text and CASE["diagnosis"] in text and '"pain": 4' in text


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.content, Exception):
            raise self.content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


def make(content):
    completions = FakeCompletions(content)
    return Director(client=SimpleNamespace(chat=SimpleNamespace(completions=completions)), model="test"), completions


def test_direct_sends_case_and_recent_turns():
    director, completions = make('{"emotion": "sad", "intensity": 0.5, "pain": 2, "discomfort": 0.6}')
    history = [
        {"role": "system", "content": "ignored"},
        {"role": "user", "content": "How much do you drink?"},
    ]
    d = director.direct(CASE, history)
    assert d["emotion"] == "sad" and d["discomfort"] == 0.6
    sent = completions.calls[0]
    assert sent["response_format"] == {"type": "json_object"}
    prompt = sent["messages"][1]["content"]
    assert "Student: How much do you drink?" in prompt and "ignored" not in prompt


def test_direct_never_raises():
    director, _ = make(RuntimeError("network down"))
    assert director.direct(CASE, [{"role": "user", "content": "Hi"}]) is None
    director, _ = make("{}")
    assert director.direct(CASE, []) is None  # nothing to react to


def test_enabled_switch(monkeypatch):
    monkeypatch.setenv("DIRECTOR", "off")
    assert not Director.enabled()
    monkeypatch.delenv("DIRECTOR")
    assert Director.enabled()
