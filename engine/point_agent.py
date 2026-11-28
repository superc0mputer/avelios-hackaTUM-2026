"""Point the ElevenLabs agent's custom LLM at this machine's tunnel.

demo.sh runs this after every tunnel start, because a Cloudflare quick tunnel gets a new
address each time. Usage: python point_agent.py https://<tunnel-host>/v1

Reads ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID from engine/.env (or the environment).
The agent keeps its stored API-key secret; only the URL changes.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

API = "https://api.elevenlabs.io/v1/convai/agents/"


def _request(url: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="PATCH" if body is not None else "GET",
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def point_agent(llm_url: str, key: str, agent_id: str) -> str:
    """Set the agent's custom-LLM URL and return the URL the agent now uses."""
    prompt = _request(API + agent_id, key)["conversation_config"]["agent"]["prompt"]
    custom = prompt.get("custom_llm") or {}
    secret = (custom.get("api_key") or {}).get("secret_id")
    if not secret:
        raise SystemExit(
            "The agent has no API key for its custom LLM. In ElevenLabs, set LLM = Custom LLM and "
            "store the value of ENGINE_API_KEY as its API key, then run this again."
        )
    # Send only what changes: a PATCH with the full custom_llm object is rejected
    body = {
        "conversation_config": {
            "agent": {
                "prompt": {
                    "llm": "custom-llm",
                    "custom_llm": {"url": llm_url, "model_id": custom.get("model_id"), "api_key": {"secret_id": secret}},
                }
            }
        }
    }
    updated = _request(API + agent_id, key, body)
    return updated["conversation_config"]["agent"]["prompt"]["custom_llm"]["url"]


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        raise SystemExit("usage: point_agent.py https://<tunnel-host>/v1")
    load_dotenv(Path(__file__).resolve().parent / ".env")
    key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    agent_id = (os.getenv("ELEVENLABS_AGENT_ID") or "").strip()
    if not key or not agent_id:
        raise SystemExit("set ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID in engine/.env")
    try:
        url = point_agent(sys.argv[1], key, agent_id)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"ElevenLabs refused the update ({error.code}): {error.read()[:300]!r}")
    print(f"ElevenLabs agent {agent_id} now calls {url}")


if __name__ == "__main__":
    main()
