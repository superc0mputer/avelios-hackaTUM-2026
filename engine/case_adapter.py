"""Turn a teacher-UI case (cases/*.json, schema 1.2) into the engine's PatientConfig.

The teacher UI (Maia) stores facts as plain lists per category plus a list of
secrets; the engine (Senan) wants staged information tiers. Mapping:

* first symptom                      -> ``spontaneous`` (what the patient opens with)
* other symptoms, history, meds,
  allergies, family history, lifestyle -> ``on_specific_query``
* secrets                            -> ``gated_secrets`` (unlock rule from the personality)
* personality type / mood / description -> ``affect_profile``

The diagnosis is never passed on: the patient must not know or reveal it.
Engine-format files (no ``schema_version``) are validated as they are.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import PatientConfig

DEFAULT_SETTING = "GP practice"

# Same wording as the disclosure hints in teacher-ui/static/app.js.
PERSONALITIES: dict[str, dict[str, Any]] = {
    "no_preference": {
        "style": "an ordinary, cooperative patient; natural everyday words, neither hides things nor over-shares",
        "cooperation": "high",
        "unlock": "An ordinary, cooperative patient; shares secrets once the student asks respectfully and specifically.",
        "triggers": ["being rushed or talked down to", "unexplained medical jargon"],
        "rapport": ["friendly, respectful questions", "listening and explaining"],
    },
    "downplays_everything": {
        "style": "short answers at first, plays symptoms down, dry humour, everyday words",
        "cooperation": "moderate",
        "unlock": "Minimizes at first; secrets emerge after specific, respectful follow-up.",
        "triggers": ["being rushed or lectured", "unexplained medical jargon"],
        "rapport": ["calm, respectful questions", "taking his or her worries seriously"],
    },
    "anxious_talkative": {
        "style": "talks a lot, worries out loud, drifts into details and side stories",
        "cooperation": "high",
        "unlock": "Volunteers context and may digress; secrets need empathetic, focused follow-up.",
        "triggers": ["vague or alarming remarks", "being cut off abruptly"],
        "rapport": ["reassurance and clear explanations", "gentle structuring of the conversation"],
    },
    "shy_reserved": {
        "style": "quiet, brief answers, hesitates before personal topics",
        "cooperation": "moderate",
        "unlock": "Gives brief answers at first; opens up with gentle rapport.",
        "triggers": ["pressure or many closed questions in a row", "judgemental reactions"],
        "rapport": ["patience and open questions", "warmth and privacy"],
    },
    "assertive": {
        "style": "direct, confident, expects clear answers, can be impatient",
        "cooperation": "moderate",
        "unlock": "Answers directly about symptoms; holds back personal details until invited.",
        "triggers": ["condescension", "wasting time"],
        "rapport": ["straightforward, competent communication", "explaining why a question matters"],
    },
    "distrustful": {
        "style": "guarded, questions the purpose of questions, short answers",
        "cooperation": "low",
        "unlock": "Stays guarded until the student explains the purpose and builds rapport.",
        "triggers": ["unexplained or intrusive questions", "feeling judged"],
        "rapport": ["explaining the purpose of questions", "consistency and honesty"],
    },
}
CUSTOM_UNLOCK = "Reveals secrets only after the student builds trust with empathetic, specific questions."

MOODS = {
    "neutral": "calm, neutral",
    "happy": "upbeat, cheerful",
    "sad": "low, sad",
    "fear": "anxious, frightened",
    "disgust": "irritated, put off",
    "anger": "annoyed, angry",
    "surprise": "surprised, unsettled",
}


def is_teacher_case(data: dict[str, Any]) -> bool:
    return "schema_version" in data and "patient" in data


def teacher_case_to_config(case: dict[str, Any], *, setting: str = DEFAULT_SETTING) -> PatientConfig:
    patient = case["patient"]
    personality = case.get("personality", {})
    ptype = personality.get("type", "custom")
    profile = PERSONALITIES.get(ptype, {})
    description = (personality.get("description") or "").strip()
    mood = MOODS.get(personality.get("mood", "neutral"), personality.get("mood", "neutral"))

    symptoms = [s for s in case.get("symptoms", []) if s.strip()]
    queried: list[str] = symptoms[1:]
    for category in ("medical_history", "medications", "allergies", "family_history", "lifestyle"):
        queried += [s for s in case.get(category, []) if s.strip()]
    secrets = [s for s in case.get("secrets", []) if s.strip()]
    life_story = (patient.get("life_story") or "").strip()
    spontaneous = symptoms[:1] or [life_story or "Has come in because something is worrying them."]

    style = profile.get("style") or description or "everyday words, natural spoken style"
    if description and profile:
        style = f"{style}. {description}"

    return PatientConfig.model_validate({
        "case_id": case["case_id"],
        "case_title": f"History-taking with {patient['name']}",
        "clinical_setting": setting,
        "chief_complaint": spontaneous[0],
        "demographics": {
            "full_name": patient["name"],
            "age": patient["age"],
            "gender": patient["gender"],
            "occupation": "patient",
            "living_situation": life_story or None,
        },
        "affect_profile": {
            "baseline_mood": mood,
            "communication_style": style,
            "cooperation_level": profile.get("cooperation", "moderate"),
            "emotional_triggers": profile.get("triggers", []),
            "rapport_builders": profile.get("rapport", []),
        },
        "information_tiers": {
            "spontaneous": spontaneous,
            "on_specific_query": queried,
            "gated_secrets": secrets,
            "unlock_condition": (profile.get("unlock") or CUSTOM_UNLOCK) if secrets else "",
        },
    })


def load_patient_config(source: str | Path | dict[str, Any]) -> PatientConfig:
    """Load a case from a path or dict in either format."""
    data = source if isinstance(source, dict) else json.loads(Path(source).read_text(encoding="utf-8"))
    if is_teacher_case(data):
        return teacher_case_to_config(data)
    return PatientConfig.model_validate(data)
