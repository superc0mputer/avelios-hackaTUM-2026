"""Cheap checks that a judge's OpenAI and ElevenLabs keys work, used by the key screen.

Each check makes one read-only request and returns a dict:
    {"ok": True, ...details}  or  {"ok": False, "error": "<short reason for the judge>"}
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

OPENAI_MODELS = "https://api.openai.com/v1/models"
ELEVENLABS_SUBSCRIPTION = "https://api.elevenlabs.io/v1/user/subscription"
TIMEOUT = 15


def _get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def _failure(error: Exception, service: str) -> dict[str, Any]:
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return {"ok": False, "error": f"{service} did not accept this key."}
        if error.code == 429:
            return {"ok": False, "error": f"{service} says this key is out of credit or rate-limited."}
        return {"ok": False, "error": f"{service} answered with error {error.code}."}
    return {"ok": False, "error": f"Could not reach {service}. Check the internet connection."}


def check_openai(key: str, model: str | None = None) -> dict[str, Any]:
    key = (key or "").strip()
    if not key:
        return {"ok": False, "error": "Enter an OpenAI API key."}
    try:
        data = _get(OPENAI_MODELS, {"Authorization": f"Bearer {key}"})
    except Exception as error:  # noqa: BLE001 - every failure becomes a message for the judge
        return _failure(error, "OpenAI")
    ids = {m.get("id") for m in data.get("data", []) if isinstance(m, dict)}
    result: dict[str, Any] = {"ok": True}
    if model:
        result["model"] = model
        result["model_available"] = model in ids
        if model not in ids:
            result["ok"] = False
            result["error"] = f"This OpenAI key has no access to the model {model}."
    return result


def check_elevenlabs(key: str) -> dict[str, Any]:
    key = (key or "").strip()
    if not key:
        return {"ok": False, "error": "Enter an ElevenLabs API key."}
    try:
        data = _get(ELEVENLABS_SUBSCRIPTION, {"xi-api-key": key})
    except Exception as error:  # noqa: BLE001
        return _failure(error, "ElevenLabs")
    used = int(data.get("character_count") or 0)
    limit = int(data.get("character_limit") or 0)
    return {
        "ok": True,
        "tier": data.get("tier"),
        "credits_left": max(0, limit - used),
        "credits_limit": limit,
    }
