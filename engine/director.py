"""Director: decides per student turn how the patient's face should react.

The patient's reply streams to ElevenLabs as plain text, so it cannot carry the
emotion. Instead, a small JSON call runs next to the reply on every student turn
and returns ``{emotion, intensity, pain, discomfort}``. The voice server sends it
to Unreal, usually before the voice arrives, so the face reacts while the patient
"thinks". The reply itself is never delayed.

The case's pain and discomfort are the floor: Unreal never shows less (VIPCase).

Environment (engine/.env):
    DIRECTOR            "off" disables it (the face keeps the case's starting mood)
    DIRECTOR_MODEL      model for the call (default: OPENAI_MODEL, then gpt-6-luna)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from llm_client import DEFAULT_MODEL, LLMClientError, _supports_reasoning_effort

log = logging.getLogger("director")

# The 12 emotions Unreal can show (README, VIPExpressions.cpp).
EMOTIONS = (
    "neutral", "happy", "sad", "fear", "disgust", "anger", "surprise",
    "boredom", "confidence", "confusion", "excitement", "playfulness",
)
MAX_INTENSITY = 2.0
RECENT_TURNS = 8

INSTRUCTIONS = f"""You direct the facial expression of a simulated patient in a medical history-taking exercise.
A medical student is interviewing the patient. Given the case and the conversation so far, decide how the
patient's FACE reacts to the student's latest turn, while the patient answers it.

Return only a JSON object:
{{"emotion": one of {list(EMOTIONS)},
 "intensity": number 0.2 to 1.5 (0.5 = clearly visible, 1 = strong, above 1.2 only for big moments),
 "pain": number 0 to 10 (how much physical pain shows in the face right now),
 "discomfort": number 0 to 1 (unease about the topic: embarrassment, a sensitive question, distrust)}}

Rules:
- Stay medically and psychologically consistent with the case: the illness, the personality, the starting mood.
- Pain comes from the illness. It rises when the student asks the patient to move, press, or recall a bad episode;
  it never drops below the case's pain.
- Discomfort rises on sensitive topics (secrets, alcohol, drugs, sex, money, family conflict, mental health) or when
  the student is rude, rushed or judgemental, and falls when the student is empathetic.
- Most turns are calm: small changes, neutral or the starting mood at 0.3 to 0.6. No exaggerated faces.
"""


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def parse_direction(text: str, floor: dict[str, float] | None = None) -> dict[str, Any] | None:
    """Turn the model's JSON into an Unreal emotion message, or None if it is unusable."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    floor = floor or {}
    emotion = str(data.get("emotion", "neutral")).strip().lower()
    return {
        "type": "emotion",
        "emotion": emotion if emotion in EMOTIONS else "neutral",
        "intensity": round(_clamp(data.get("intensity"), 0.0, MAX_INTENSITY, 0.5), 2),
        "pain": round(max(floor.get("pain", 0.0), _clamp(data.get("pain"), 0.0, 10.0, 0.0)), 1),
        "discomfort": round(max(floor.get("discomfort", 0.0), _clamp(data.get("discomfort"), 0.0, 1.0, 0.0)), 2),
    }


def describe_case(case: dict[str, Any] | None) -> str:
    """What the director needs to know about the patient (teacher-UI case or engine case)."""
    if not case:
        return "No case details."
    if "schema_version" in case:
        patient = case.get("patient") or {}
        personality = case.get("personality") or {}
        lines = [
            f"Patient: {patient.get('name')}, {patient.get('age')}, {patient.get('gender')}.",
            f"Diagnosis (the student does not know it): {case.get('diagnosis')}.",
            f"Personality: {personality.get('type')}. {personality.get('description') or ''}".strip(),
            f"Starting mood: {personality.get('mood', 'neutral')}.",
            "Symptoms: " + " ".join(case.get("symptoms") or []),
        ]
        if case.get("secrets"):
            lines.append("Sensitive topics (secrets): " + " ".join(case["secrets"]))
        if isinstance(case.get("presentation"), dict):
            lines.append("Presentation: " + json.dumps(case["presentation"], ensure_ascii=False))
        return "\n".join(lines)
    demo = case.get("demographics") or {}
    affect = case.get("affect_profile") or {}
    tiers = case.get("information_tiers") or {}
    return "\n".join([
        f"Patient: {demo.get('full_name')}, {demo.get('age')}, {demo.get('gender')}.",
        f"Chief complaint: {case.get('chief_complaint')}.",
        f"Mood: {affect.get('baseline_mood')}. Style: {affect.get('communication_style')}.",
        f"Pain: {affect.get('pain_level')}/10." if affect.get("pain_level") is not None else "",
        "Sensitive topics (secrets): " + " ".join(tiers.get("gated_secrets") or []),
    ]).strip()


def case_floor(case: dict[str, Any] | None) -> dict[str, float]:
    """The case's own pain and discomfort, which the face never goes below."""
    presentation = (case or {}).get("presentation") or {}
    return {
        "pain": _clamp(presentation.get("pain"), 0.0, 10.0, 0.0),
        "discomfort": _clamp(presentation.get("discomfort"), 0.0, 1.0, 0.0),
    }


class Director:
    """One JSON call per student turn. Thread-safe as long as the OpenAI client is."""

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        self.model = (model or os.getenv("DIRECTOR_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL).strip()
        self._client = client

    @staticmethod
    def enabled() -> bool:
        return (os.getenv("DIRECTOR") or "on").strip().lower() not in ("off", "0", "false", "no")

    def _openai(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            key = (os.getenv("OPENAI_API_KEY") or "").strip()
            if not key:
                raise LLMClientError("OPENAI_API_KEY is not set")
            self._client = OpenAI(api_key=key, base_url=(os.getenv("OPENAI_BASE_URL") or "").strip() or None)
        return self._client

    def direct(self, case: dict[str, Any] | None, history: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The face for this turn, or None when the call fails (the face then keeps what it has)."""
        turns = [
            f"{'Student' if m.get('role') == 'user' else 'Patient'}: {m['content'].strip()}"
            for m in history
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()
        ][-RECENT_TURNS:]
        if not turns:
            return None
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": f"CASE\n{describe_case(case)}\n\nCONVERSATION\n" + "\n".join(turns)},
            ],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 120,
        }
        if _supports_reasoning_effort(self.model):
            request["reasoning_effort"] = "none"
        try:
            response = self._openai().chat.completions.create(**request)
            text = response.choices[0].message.content
        except Exception as exc:  # network, key, model errors: never break the conversation
            log.warning("director failed: %s", exc)
            return None
        direction = parse_direction(text, case_floor(case))
        if direction is None:
            log.warning("director returned unusable output: %.120s", text)
        return direction
