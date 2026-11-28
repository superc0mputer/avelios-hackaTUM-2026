"""Shared Pydantic v2 data contract between lecturer configuration and the prompt builder."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ContractModel(BaseModel):
    """Base model enforcing strict field validation across the schema contract."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Demographics(_ContractModel):
    """Patient biographical and social background."""

    full_name: str = Field(
        ...,
        min_length=1,
        description="Full name of the simulated patient persona.",
    )
    age: int = Field(
        ...,
        ge=0,
        le=120,
        description="Patient age in years.",
    )
    gender: str = Field(
        ...,
        min_length=1,
        description="Patient gender identity as presented in the case.",
    )
    occupation: str = Field(
        ...,
        min_length=1,
        description="Current or primary occupation of the patient.",
    )
    living_situation: str | None = Field(
        default=None,
        description="Optional summary of household, family, or work context.",
    )


class AffectProfile(_ContractModel):
    """Behavioral, emotional, and communication profile for realistic acting."""

    baseline_mood: str = Field(
        ...,
        min_length=1,
        description="Default emotional baseline at the start of the encounter.",
    )
    communication_style: str = Field(
        ...,
        min_length=1,
        description="How the patient typically speaks and responds to questions.",
    )
    cooperation_level: Literal["low", "moderate", "high"] = Field(
        default="moderate",
        description="Overall willingness to engage with medical questioning.",
    )
    health_literacy: Literal["low", "average", "high"] = Field(
        default="low",
        description="Familiarity with medical terminology and clinical concepts.",
    )
    pain_level: int | None = Field(
        default=None,
        ge=0,
        le=10,
        description="Optional subjective pain or discomfort score on a 0-10 scale.",
    )
    emotional_triggers: list[str] = Field(
        default_factory=list,
        description="Student behaviors or topics that make the patient defensive or guarded.",
    )
    rapport_builders: list[str] = Field(
        default_factory=list,
        description="Student behaviors that build trust and encourage openness.",
    )


class InformationTiers(_ContractModel):
    """Staged disclosure rules controlling what the patient reveals and when."""

    spontaneous: list[str] = Field(
        ...,
        min_length=1,
        description="Tier 1 facts the patient shares readily on open-ended prompts.",
    )
    on_specific_query: list[str] = Field(
        default_factory=list,
        description="Tier 2 facts revealed only when the student asks specifically.",
    )
    gated_secrets: list[str] = Field(
        default_factory=list,
        description="Tier 3 sensitive facts withheld until the unlock condition is met.",
    )
    unlock_condition: str = Field(
        default="",
        description="Condition that must be satisfied before disclosing gated secrets.",
    )
    unknowns: list[str] = Field(
        default_factory=list,
        description="Details the patient genuinely does not know and must not invent.",
    )

    @model_validator(mode="after")
    def _validate_unlock_condition(self) -> "InformationTiers":
        """Ensure gated secrets always define a non-empty unlock condition."""
        if self.gated_secrets and not self.unlock_condition:
            raise ValueError(
                "unlock_condition must be non-empty when gated_secrets are provided."
            )
        return self


class PatientConfig(_ContractModel):
    """Top-level simulated patient case contract."""

    case_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the training case.",
    )
    case_title: str = Field(
        ...,
        min_length=1,
        description="Human-readable title of the clinical training scenario.",
    )
    language: str = Field(
        default="English",
        min_length=1,
        description="Language the simulated patient speaks during the encounter.",
    )
    clinical_setting: str = Field(
        ...,
        min_length=1,
        description="Clinical environment where the history-taking takes place.",
    )
    chief_complaint: str = Field(
        ...,
        min_length=1,
        description="Primary presenting complaint bringing the patient in.",
    )
    opening_line: str | None = Field(
        default=None,
        description="Optional characteristic opening remark for the case.",
    )
    demographics: Demographics = Field(
        ...,
        description="Patient demographic details.",
    )
    affect_profile: AffectProfile = Field(
        ...,
        description="Emotional tone, literacy, triggers, and rapport profile.",
    )
    information_tiers: InformationTiers = Field(
        ...,
        description="Tiered medical and emotional disclosure rules.",
    )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "PatientConfig":
        """Load and validate a PatientConfig from a UTF-8 JSON file."""
        file_path = Path(path)
        raw_json = file_path.read_text(encoding="utf-8")
        return cls.model_validate_json(raw_json)

    def to_json_file(self, path: str | Path) -> None:
        """Serialize this PatientConfig to a formatted UTF-8 JSON file."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
