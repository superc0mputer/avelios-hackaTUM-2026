"""Builds a strict acting system prompt from a validated PatientConfig via Jinja2."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from models import PatientConfig
from state_manager import ConversationState

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_TEMPLATE_NAME = "system_prompt.j2"
_MULTI_BLANK_LINE_RE = re.compile(r"\n{3,}")


@lru_cache(maxsize=4)
def _build_environment(templates_dir: Path = PROMPTS_DIR) -> Environment:
    """Create a cached Jinja2 environment for plain-text prompt templates."""
    return Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build_system_prompt(
    config: PatientConfig,
    *,
    state: ConversationState | None = None,
    template_name: str = DEFAULT_TEMPLATE_NAME,
    templates_dir: Path | None = None,
) -> str:
    """Generate a strict simulated-patient system prompt from a PatientConfig."""
    env = _build_environment(templates_dir or PROMPTS_DIR)
    template = env.get_template(template_name)
    has_secrets = bool(config.information_tiers.gated_secrets)
    tier3_unlocked = bool(state.tier3_unlocked) if state is not None else False
    rendered = template.render(
        config=config,
        demo=config.demographics,
        affect=config.affect_profile,
        tiers=config.information_tiers,
        state=state,
        has_secrets=has_secrets,
        tier3_unlocked=tier3_unlocked,
    )
    return _MULTI_BLANK_LINE_RE.sub("\n\n", rendered).strip()
