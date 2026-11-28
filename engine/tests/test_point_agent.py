"""point_agent.py sends only the URL change and keeps the agent's stored secret (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import point_agent  # noqa: E402


def fake_agent(custom_llm):
    return {"conversation_config": {"agent": {"prompt": {"llm": "custom-llm", "custom_llm": custom_llm}}}}


def test_patch_keeps_secret_and_sets_url(monkeypatch):
    calls = []

    def request(url, key, body=None):
        calls.append((url, key, body))
        if body is None:
            return fake_agent({"url": "https://old.trycloudflare.com/v1", "model_id": "patient",
                               "api_key": {"secret_id": "sec_1", "name": "engine"}, "request_headers": {}})
        return fake_agent(body["conversation_config"]["agent"]["prompt"]["custom_llm"])

    monkeypatch.setattr(point_agent, "_request", request)
    assert point_agent.point_agent("https://new.trycloudflare.com/v1", "xi", "agent_1") == "https://new.trycloudflare.com/v1"

    url, key, body = calls[-1]
    assert url.endswith("/agent_1") and key == "xi"
    assert body == {"conversation_config": {"agent": {"prompt": {
        "llm": "custom-llm",
        "custom_llm": {"url": "https://new.trycloudflare.com/v1", "model_id": "patient", "api_key": {"secret_id": "sec_1"}},
    }}}}


def test_agent_without_secret_is_refused(monkeypatch):
    monkeypatch.setattr(point_agent, "_request", lambda url, key, body=None: fake_agent({"url": "x"}))
    with pytest.raises(SystemExit, match="ENGINE_API_KEY"):
        point_agent.point_agent("https://new.trycloudflare.com/v1", "xi", "agent_1")
