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

TEACHER_CASES = sorted(p for p in CASES_DIR.glob("case-*.json"))


@pytest.mark.parametrize("path", TEACHER_CASES, ids=lambda p: p.name)
def test_teacher_case_maps_to_patient_config(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    config = load_patient_config(path)
    tiers = config.information_tiers
    assert config.case_id == case["case_id"]
    assert config.demographics.full_name == case["patient"]["name"]
    assert tiers.spontaneous == case["symptoms"][:1]
    assert tiers.gated_secrets == case["secrets"]
    assert tiers.unlock_condition
    for category in ("medical_history", "medications", "allergies", "family_history", "lifestyle"):
        for fact in case[category]:
            assert fact in tiers.on_specific_query

    prompt = build_system_prompt(config)
    assert case["diagnosis"] not in prompt, "the patient must not know the diagnosis"
    assert case["patient"]["name"] in prompt


def test_engine_format_still_loads():
    config = load_patient_config(ENGINE_DIR / "data" / "mock_gerhard_mueller.json")
    assert config.case_id == "gerhard_mueller_acs_01"
