"""Teacher-UI cases (cases/*.json) must run in the engine."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
CASES_DIR = ENGINE_DIR.parent / "cases"
sys.path.insert(0, str(ENGINE_DIR))
os.environ["VOICE_SERVER_NO_AUTOLOAD"] = "1"

from case_adapter import load_patient_config  # noqa: E402
from prompt_builder import build_system_prompt  # noqa: E402

# The example cases in the repo (locally saved test cases may differ).
TEACHER_CASES = [CASES_DIR / "case-001.json", CASES_DIR / "case-002.json"]


@pytest.mark.parametrize("path", TEACHER_CASES, ids=lambda p: p.name)
def test_teacher_case_maps_to_patient_config(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    config = load_patient_config(path)
    tiers = config.information_tiers
    assert config.case_id == case["case_id"]
    assert config.demographics.full_name == case["patient"]["name"]
    assert tiers.spontaneous == case["symptoms"][:1]
    assert tiers.gated_secrets == case["secrets"]
    assert bool(tiers.unlock_condition) == bool(case["secrets"])
    for category in ("medical_history", "medications", "allergies", "family_history", "lifestyle"):
        for fact in case[category]:
            assert fact in tiers.on_specific_query

    prompt = build_system_prompt(config)
    assert case["diagnosis"] not in prompt, "the patient must not know the diagnosis"
    assert case["patient"]["name"] in prompt


def test_engine_format_still_loads():
    config = load_patient_config(ENGINE_DIR / "data" / "mock_gerhard_mueller.json")
    assert config.case_id == "gerhard_mueller_acs_01"


def test_no_preference_personality():
    from jsonschema import Draft202012Validator

    case = json.loads((CASES_DIR / "case-001.json").read_text(encoding="utf-8"))
    case["personality"] = {"type": "no_preference", "description": "", "mood": "neutral"}
    schema = json.loads((CASES_DIR / "patient-case.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(case))
    config = load_patient_config(case)
    assert "ordinary" in config.affect_profile.communication_style
    assert config.affect_profile.cooperation_level == "high"
