"""Encapsulated OpenAI chat client for the simulated patient actor."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 250
DEFAULT_REASONING_EFFORT = "none"
_REASONING_MODEL_PREFIXES = ("gpt-6", "gpt-5", "o1", "o3", "o4")


class LLMClientError(RuntimeError):
    """Raised when the LLM client cannot be initialized or fails during a turn."""


def _supports_reasoning_effort(model: str) -> bool:
    """Return True if the model family supports the OpenAI reasoning_effort parameter."""
    normalized = model.strip().lower().rsplit("/", 1)[-1]
    return normalized.startswith(_REASONING_MODEL_PREFIXES)


def _resolve_temperature(temperature: float | None) -> float:
    """Resolve sampling temperature from argument, environment, or default."""
    if temperature is not None:
        return temperature
    raw_temp = os.getenv("OPENAI_TEMPERATURE")
    if raw_temp is None or not raw_temp.strip():
        return DEFAULT_TEMPERATURE
    try:
        return float(raw_temp)
    except ValueError as exc:
        raise LLMClientError(
            f"Invalid OPENAI_TEMPERATURE value {raw_temp!r}; expected a float."
        ) from exc


def _resolve_reasoning_effort(reasoning_effort: str | None, model: str) -> str | None:
    """Resolve reasoning effort from argument, environment, or model-aware default."""
    if reasoning_effort is not None:
        cleaned = reasoning_effort.strip()
        if not cleaned:
            raise ValueError("reasoning_effort must not be empty.")
        return cleaned
    raw_effort = os.getenv("OPENAI_REASONING_EFFORT")
    if raw_effort is not None and raw_effort.strip():
        return raw_effort.strip()
    if _supports_reasoning_effort(model):
        return DEFAULT_REASONING_EFFORT
    return None


class ChatActorClient:
    """Stateful multi-turn chat wrapper around the official OpenAI SDK."""

    def __init__(
        self,
        system_prompt: str,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        reasoning_effort: str | None = None,
        client: Any | None = None,
    ) -> None:
        load_dotenv()

        cleaned_prompt = system_prompt.strip()
        if not cleaned_prompt:
            raise ValueError("system_prompt must not be empty.")

        resolved_model = (model or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL).strip()
        if not resolved_model:
            resolved_model = DEFAULT_MODEL

        self._model = resolved_model
        self._temperature = _resolve_temperature(temperature)
        self._max_tokens = max_tokens
        self._reasoning_effort = _resolve_reasoning_effort(reasoning_effort, resolved_model)
        self._system_prompt = cleaned_prompt

        if client is not None:
            self._client = client
        else:
            resolved_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
            if not resolved_key:
                raise LLMClientError(
                    "OPENAI_API_KEY is not set. Copy .env.example to .env and add your OpenAI API key."
                )
            resolved_base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "").strip() or None
            self._client = OpenAI(api_key=resolved_key, base_url=resolved_base_url)

        self._messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt}
        ]

    @property
    def model(self) -> str:
        """Return the configured OpenAI chat model name."""
        return self._model

    @property
    def reasoning_effort(self) -> str | None:
        """Return the configured reasoning effort level, if any."""
        return self._reasoning_effort

    @property
    def system_prompt(self) -> str:
        """Return the active system prompt."""
        return self._system_prompt

    @property
    def messages(self) -> list[dict[str, str]]:
        """Return a shallow copy of the current conversation history."""
        return [dict(msg) for msg in self._messages]

    def reset(self, system_prompt: str | None = None) -> None:
        """Clear conversation history and optionally update the system prompt."""
        if system_prompt is not None:
            cleaned = system_prompt.strip()
            if not cleaned:
                raise ValueError("system_prompt must not be empty.")
            self._system_prompt = cleaned
        self._messages = [{"role": "system", "content": self._system_prompt}]

    def send_message(self, user_message: str) -> str:
        """Send a student turn to the model and return the patient's reply."""
        cleaned = user_message.strip()
        if not cleaned:
            raise ValueError("user_message must not be empty.")

        pending_messages = [*self._messages, {"role": "user", "content": cleaned}]

        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": pending_messages,
            "max_completion_tokens": self._max_tokens,
        }
        if self._reasoning_effort is not None:
            request_kwargs["reasoning_effort"] = self._reasoning_effort
        if self._reasoning_effort in (None, "none"):
            request_kwargs["temperature"] = self._temperature

        try:
            response = self._client.chat.completions.create(**request_kwargs)
        except OpenAIError as exc:
            raise LLMClientError(f"OpenAI API request failed: {exc}") from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise LLMClientError("OpenAI API returned no choices.")

        content = getattr(choices[0].message, "content", None)
        reply = content.strip() if isinstance(content, str) else ""
        if not reply:
            raise LLMClientError("OpenAI API returned an empty reply.")

        self._messages = [*pending_messages, {"role": "assistant", "content": reply}]
        return reply
