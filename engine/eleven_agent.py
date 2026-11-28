"""Set up the patient agent inside the judge's own ElevenLabs account.

The packaged app has no server of ours, so ElevenLabs cannot call our engine. Instead the
agent's custom LLM is OpenAI itself, called with the judge's OpenAI key (stored as a secret in
the judge's ElevenLabs workspace). The engine still builds the patient's system prompt from the
case and writes it into the agent whenever a case is loaded (the app has a single user), so the
prompt never passes through the browser.

    agent_id = ensure_agent(eleven_key, openai_key, model)   # once, on first start
    set_prompt(eleven_key, agent_id, system_prompt)          # when a case is loaded
    url = signed_url(eleven_key, agent_id)                   # before each conversation

NOT YET TESTED against the live API (field shapes from ElevenLabs' docs and engine/point_agent.py
on branch 60): check the custom_llm url form and free-plan support with a real key.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = "https://api.elevenlabs.io/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
SECRET_NAME = "VIP_PATIENT_OPENAI_KEY"
AGENT_NAME = "VIP Patient (local app)"
# A premade ElevenLabs voice (every account has it); per-case voices can come later.
DEFAULT_VOICE_ID = "cjVigY5qzO86Huf0OWal"
TIMEOUT = 30


class ElevenLabsError(RuntimeError):
    pass


def _request(method: str, path: str, key: str, body: dict | None = None, query: dict | None = None) -> dict[str, Any]:
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"xi-api-key": key, "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read()[:300].decode("utf-8", "replace")
        raise ElevenLabsError(f"ElevenLabs refused {method} {path} ({error.code}): {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ElevenLabsError("Could not reach ElevenLabs. Check the internet connection.") from error


def create_openai_secret(eleven_key: str, openai_key: str) -> str:
    result = _request("POST", "/convai/secrets", eleven_key, {"type": "new", "name": SECRET_NAME, "value": openai_key})
    return result["secret_id"]


def agent_config(secret_id: str, model: str, voice_id: str = DEFAULT_VOICE_ID) -> dict[str, Any]:
    return {
        "name": AGENT_NAME,
        "conversation_config": {
            "agent": {
                # The patient waits for the student to speak first
                "first_message": "",
                "language": "en",
                "prompt": {
                    "prompt": "You are a patient. The real instructions arrive with each conversation.",
                    "llm": "custom-llm",
                    "custom_llm": {"url": OPENAI_BASE_URL, "model_id": model, "api_key": {"secret_id": secret_id}},
                },
            },
            "tts": {"voice_id": voice_id},
        },
        "platform_settings": {
            # Only the app (with the judge's key) can start conversations, through signed URLs
            "auth": {"enable_auth": True},
        },
    }


def ensure_agent(eleven_key: str, openai_key: str, model: str, agent_id: str | None = None) -> str:
    """Return a working agent id: the stored one if it still exists, else a newly created agent."""
    if agent_id:
        try:
            _request("GET", f"/convai/agents/{agent_id}", eleven_key)
            return agent_id
        except ElevenLabsError:
            pass  # deleted or another account: create a new one
    secret_id = create_openai_secret(eleven_key, openai_key)
    return _request("POST", "/convai/agents/create", eleven_key, agent_config(secret_id, model))["agent_id"]


def set_prompt(eleven_key: str, agent_id: str, system_prompt: str) -> None:
    """Give the agent the current case's patient prompt (the app has one user, so no overrides needed)."""
    body = {"conversation_config": {"agent": {"first_message": "", "prompt": {"prompt": system_prompt}}}}
    _request("PATCH", f"/convai/agents/{agent_id}", eleven_key, body)


def signed_url(eleven_key: str, agent_id: str) -> str:
    result = _request("GET", "/convai/conversation/get-signed-url", eleven_key, query={"agent_id": agent_id})
    return result["signed_url"]
