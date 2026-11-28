"""Programmatic conversation state management and Tier 3 hard-gating."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_client import _supports_reasoning_effort
from models import PatientConfig

EmotionalStance = Literal["defensive", "guarded", "neutral", "warming_up", "open"]
EvaluatorMode = Literal["hybrid", "heuristic", "llm"]
TransitionSource = Literal["heuristic", "llm"]

_COOPERATION_DEFAULTS: dict[str, tuple[int, int, EmotionalStance]] = {
    "high": (30, 60, "neutral"),
    "moderate": (20, 60, "guarded"),
    "low": (10, 70, "guarded"),
}

_MAX_POSITIVE_DELTA = 55
_MIN_NEGATIVE_DELTA = -35
_RECENT_TURNS_LIMIT = 4

_TRIVIAL_UTTERANCES = frozenset({
    "hi", "hello", "hey", "hallo", "guten tag", "guten morgen", "good morning",
    "good afternoon", "ok", "okay", "yes", "no", "ja", "nein", "thanks",
    "thank you", "danke", "danke schön", "sure", "alright", "alles klar",
})

_VALIDATION_PATTERNS = (
    re.compile(r"\bi can see (?:that )?(?:this|it)\b.{0,40}\b(?:hard|difficult|stress\w*|worr\w*|scary|overwhelming|heavy|lot)\b", re.IGNORECASE),
    re.compile(r"\bthat sounds (?:really |very )?(?:hard|tough|scary|stressful|difficult|overwhelming|exhausting)\b", re.IGNORECASE),
    re.compile(r"\bi hear you\b", re.IGNORECASE),
    re.compile(r"\bcompletely understandable\b", re.IGNORECASE),
    re.compile(r"\bmakes (?:total |complete )?sense that you\b", re.IGNORECASE),
    re.compile(r"\bi understand how (?:hard|scary|stressful|worrying)\b", re.IGNORECASE),
    re.compile(r"\bmust be (?:really )?(?:hard|scary|stressful|frightening)\b", re.IGNORECASE),
    re.compile(r"\bich merke\b.{0,45}\b(?:belastet|schwer|angst|sorgen|stress|mitnimmt)\b", re.IGNORECASE),
    re.compile(r"\bdas klingt\b.{0,30}\b(?:schwer|belastend|beängstigend|anstrengend|schlimm)\b", re.IGNORECASE),
    re.compile(r"\bkann (?:ich )?(?:gut )?verstehen\b", re.IGNORECASE),
    re.compile(r"\bvöllig verständlich\b", re.IGNORECASE),
    re.compile(r"\bes ist (?:ganz )?normal\b.{0,35}\b(?:angst|sorgen)\b", re.IGNORECASE),
    re.compile(r"\bdas muss (?:sehr )?(?:schwer|belastend|beängstigend)\b", re.IGNORECASE),
)

_SAFETY_TIME_PATTERNS = (
    re.compile(r"\btake your time\b", re.IGNORECASE),
    re.compile(r"\bno rush\b", re.IGNORECASE),
    re.compile(r"\bsafe space\b", re.IGNORECASE),
    re.compile(r"\bconfidential\b", re.IGNORECASE),
    re.compile(r"\bnot here to judge\b", re.IGNORECASE),
    re.compile(r"\bwon['’]t judge\b", re.IGNORECASE),
    re.compile(r"\bonly share what you['’]re comfortable\b", re.IGNORECASE),
    re.compile(r"\bnehmen sie sich (?:gerne )?(?:alle )?zeit\b", re.IGNORECASE),
    re.compile(r"\bkein stress\b", re.IGNORECASE),
    re.compile(r"\bkeine eile\b", re.IGNORECASE),
    re.compile(r"\bunter uns\b", re.IGNORECASE),
    re.compile(r"\bschweigepflicht\b", re.IGNORECASE),
    re.compile(r"\bvertraulich\b", re.IGNORECASE),
    re.compile(r"\bverurteile sie nicht\b", re.IGNORECASE),
    re.compile(r"\bohne vorwurf\b", re.IGNORECASE),
)

_WORRY_INQUIRY_PATTERNS = (
    re.compile(r"\bwhat (?:are you most worried|worries you|scares you|frightens you|is on your mind)\b", re.IGNORECASE),
    re.compile(r"\bhow (?:are you feeling|does that make you feel|are you coping)\b", re.IGNORECASE),
    re.compile(r"\bis there anything (?:you['’]re worried|else weighing|bothering you)\b", re.IGNORECASE),
    re.compile(r"\bwovor haben sie\b.{0,25}\bangst\b", re.IGNORECASE),
    re.compile(r"\bwas macht ihnen\b.{0,25}\bsorgen\b", re.IGNORECASE),
    re.compile(r"\bwas belastet sie\b", re.IGNORECASE),
    re.compile(r"\bwie geht es ihnen damit\b", re.IGNORECASE),
    re.compile(r"\bhaben sie angst\b", re.IGNORECASE),
)

_PURPOSE_PATTERNS = (
    re.compile(r"\bthe reason i(?:'m| am) asking\b", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am) asking because\b", re.IGNORECASE),
    re.compile(r"\bhelps me understand\b", re.IGNORECASE),
    re.compile(r"\bso we can (?:help|figure out|make sure)\b", re.IGNORECASE),
    re.compile(r"\bwould it be okay if i ask\b", re.IGNORECASE),
    re.compile(r"\bich frage (?:deshalb|weil)\b", re.IGNORECASE),
    re.compile(r"\bder grund\b.{0,25}\bfrage\b", re.IGNORECASE),
    re.compile(r"\bhilft mir\b.{0,25}\bzu verstehen\b", re.IGNORECASE),
    re.compile(r"\bdamit wir\b.{0,25}\bhelfen\b", re.IGNORECASE),
    re.compile(r"\bist es in ordnung,\s*wenn ich\b", re.IGNORECASE),
)

_WARMTH_PATTERNS = (
    re.compile(r"\bi['’]m sorry (?:you['’]re|to hear|that you)\b", re.IGNORECASE),
    re.compile(r"\bthank you for (?:telling|sharing|being honest)\b", re.IGNORECASE),
    re.compile(r"\bi appreciate (?:you|your honesty)\b", re.IGNORECASE),
    re.compile(r"\bdas tut mir leid\b", re.IGNORECASE),
    re.compile(r"\bdanke\b.{0,30}\b(?:ehrlich|offen|erzählen|vertrauen)\b", re.IGNORECASE),
    re.compile(r"\bich nehme\b.{0,25}\bernst\b", re.IGNORECASE),
)

_LECTURING_PATTERNS = (
    re.compile(r"\bwhy didn['’]t you\b", re.IGNORECASE),
    re.compile(r"\byou should have\b", re.IGNORECASE),
    re.compile(r"\byou have to take\b", re.IGNORECASE),
    re.compile(r"\byou must stop\b", re.IGNORECASE),
    re.compile(r"\bthat['’]s irresponsible\b", re.IGNORECASE),
    re.compile(r"\byou['’]re not complying\b", re.IGNORECASE),
    re.compile(r"\bwarum haben sie nicht\b", re.IGNORECASE),
    re.compile(r"\bsie hätten\b.{0,25}\bmüssen\b", re.IGNORECASE),
    re.compile(r"\bsie müssen (?:aber|unbedingt)\b", re.IGNORECASE),
    re.compile(r"\bdas ist unverantwortlich\b", re.IGNORECASE),
    re.compile(r"\bselbst schuld\b", re.IGNORECASE),
)

_DISMISSIVE_PATTERNS = (
    re.compile(r"\bhurry up\b", re.IGNORECASE),
    re.compile(r"\bcalm down\b", re.IGNORECASE),
    re.compile(r"\bit['’]s nothing to worry about\b", re.IGNORECASE),
    re.compile(r"\bstop worrying\b", re.IGNORECASE),
    re.compile(r"\bjust answer (?:yes or no|the question)\b", re.IGNORECASE),
    re.compile(r"\bwe don['’]t have time\b", re.IGNORECASE),
    re.compile(r"\bbeeilen sie sich\b", re.IGNORECASE),
    re.compile(r"\bberuhigen sie sich\b", re.IGNORECASE),
    re.compile(r"\bstellen sie sich nicht so an\b", re.IGNORECASE),
    re.compile(r"\bhalb so schlimm\b", re.IGNORECASE),
    re.compile(r"\bkeine zeit\b", re.IGNORECASE),
    re.compile(r"\bantworten sie einfach\b", re.IGNORECASE),
)

_JARGON_PATTERN = re.compile(
    r"\b(?:myocardial infarction|angina pectoris|dyspnea|dyspnoe|hypertension|hypertonie|"
    r"syncope|synkope|thoraxschmerz|compliance|coronary artery|ischemia|ischämie|"
    r"tachycardia|tachykardie)\b",
    re.IGNORECASE,
)

_TOKEN_RE = re.compile(r"[a-zA-ZäöüÄÖÜß]{4,}")
_STOPWORDS = frozenset({
    "about", "after", "around", "because", "been", "being", "does", "done", "each",
    "feels", "from", "have", "having", "into", "just", "known", "last", "more",
    "most", "much", "often", "only", "over", "same", "since", "some", "sometimes",
    "that", "them", "then", "there", "these", "they", "this", "time", "very",
    "want", "wants", "week", "weeks", "were", "what", "when", "where", "which",
    "while", "with", "would", "your", "aber", "alle", "also", "auch", "beim",
    "dass", "dein", "deine", "denn", "diese", "dieser", "doch", "durch", "eine",
    "einem", "einen", "einer", "eines", "etwas", "euch", "euer", "gegen", "habe",
    "haben", "hatte", "hier", "ihnen", "ihre", "immer", "kann", "kein", "keine",
    "macht", "mein", "meine", "mich", "mehr", "muss", "nach", "nicht", "noch",
    "oder", "ohne", "sehr", "sein", "seine", "sich", "sind", "über", "unter",
    "viel", "viele", "weil", "wenn", "wird", "wurde",
})


class StateTransition(BaseModel):
    """Summary of state changes caused by a single student turn."""

    model_config = ConfigDict(extra="forbid")

    turn_number: int
    trust_delta: int
    trust_before: int
    trust_after: int
    newly_unlocked_tier3: bool
    source: TransitionSource = "heuristic"
    signals: list[str] = Field(default_factory=list)
    reason: str


class ConversationState(BaseModel):
    """Live programmatic state tracked across an interview session."""

    model_config = ConfigDict(extra="forbid")

    turn_count: int = 0
    trust_score: int = Field(ge=0, le=100)
    unlock_threshold: int = Field(ge=1, le=100)
    tier3_unlocked: bool = False
    unlock_reason: str | None = None
    emotional_stance: EmotionalStance
    triggered_events: list[str] = Field(default_factory=list)
    disclosed_facts: list[str] = Field(default_factory=list)
    last_transition: StateTransition | None = None


def _derive_stance(
    trust_score: int, unlock_threshold: int, last_delta: int
) -> EmotionalStance:
    """Map trust score and recent delta to the patient's current emotional stance."""
    if last_delta <= -15 or trust_score < 15:
        return "defensive"
    if trust_score >= unlock_threshold:
        return "open"
    if trust_score >= unlock_threshold - 20:
        return "warming_up"
    if trust_score >= 25:
        return "neutral"
    return "guarded"


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _is_trivial_utterance(text: str) -> bool:
    """Return True for brief greetings/acknowledgements that never warrant an LLM judge call."""
    normalized = re.sub(r"[.!?,;:]+$", "", text.strip().lower())
    if not normalized:
        return True
    if normalized in _TRIVIAL_UTTERANCES:
        return True
    words = normalized.split()
    return len(words) <= 3 and all(w in _TRIVIAL_UTTERANCES for w in words)


def evaluate_student_turn_heuristic(
    user_message: str, config: PatientConfig
) -> tuple[int, list[str], str]:
    """Deterministically score a student turn in English or German with zero latency."""
    text = user_message.strip()
    if not text:
        return 0, [], "Empty student turn."

    delta = 0
    signals: list[str] = []
    reasons: list[str] = []

    if _matches_any(text, _VALIDATION_PATTERNS):
        delta += 35
        signals.append("active_validation")
        reasons.append("validated patient emotions")

    if _matches_any(text, _SAFETY_TIME_PATTERNS):
        delta += 20
        signals.append("offered_time_or_safety")
        reasons.append("offered time/safety")

    if _matches_any(text, _WORRY_INQUIRY_PATTERNS):
        delta += 20
        signals.append("asked_about_worries")
        reasons.append("asked empathetically about worries/feelings")

    if _matches_any(text, _PURPOSE_PATTERNS):
        delta += 15
        signals.append("explained_purpose")
        reasons.append("explained purpose of questioning")

    if _matches_any(text, _WARMTH_PATTERNS):
        delta += 15
        signals.append("empathy")
        reasons.append("expressed warmth/empathy")

    if _matches_any(text, _LECTURING_PATTERNS):
        delta -= 20
        signals.append("blaming_or_lecturing")
        reasons.append("lectured or blamed patient")

    if _matches_any(text, _DISMISSIVE_PATTERNS):
        delta -= 20
        signals.append("dismissive_or_rushed")
        reasons.append("rushed or dismissed patient concerns")

    if config.affect_profile.health_literacy == "low" and _JARGON_PATTERN.search(text):
        delta -= 10
        signals.append("unexplained_jargon")
        reasons.append("used unexplained medical jargon")

    if delta > _MAX_POSITIVE_DELTA:
        delta = _MAX_POSITIVE_DELTA
    elif delta < _MIN_NEGATIVE_DELTA:
        delta = _MIN_NEGATIVE_DELTA

    reason = "; ".join(reasons) if reasons else "neutral clinical questioning"
    return delta, signals, reason


def _significant_tokens(text: str) -> set[str]:
    return {
        tok.lower()
        for tok in _TOKEN_RE.findall(text)
        if tok.lower() not in _STOPWORDS
    }


def _strip_json_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _build_initial_state(config: PatientConfig) -> ConversationState:
    cooperation = config.affect_profile.cooperation_level
    initial_trust, threshold, initial_stance = _COOPERATION_DEFAULTS.get(
        cooperation, (20, 60, "guarded")
    )
    return ConversationState(
        turn_count=0,
        trust_score=initial_trust,
        unlock_threshold=threshold,
        tier3_unlocked=False,
        unlock_reason=None,
        emotional_stance=initial_stance,
        triggered_events=[],
        disclosed_facts=[],
        last_transition=None,
    )


class StateManager:
    """Tracks rapport, emotional stance, fact disclosures, and Tier 3 unlock gating."""

    def __init__(
        self,
        config: PatientConfig,
        *,
        evaluator_mode: str | None = None,
        llm_client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self.config = config
        resolved_mode = (
            evaluator_mode
            or os.getenv("STATE_EVALUATOR_MODE")
            or "hybrid"
        ).strip().lower()
        self.evaluator_mode: EvaluatorMode = (
            resolved_mode if resolved_mode in ("hybrid", "heuristic", "llm") else "hybrid"  # type: ignore[assignment]
        )
        self._llm_client = llm_client
        self._model = (
            model
            or os.getenv("OPENAI_STATE_MODEL")
            or os.getenv("OPENAI_MODEL")
            or "gpt-6-luna"
        ).strip()
        self.state = _build_initial_state(config)
        self._processed_turns: list[tuple[str, str]] = []
        self._recent_turns: list[tuple[str, str]] = []

    def set_llm_client(self, llm_client: Any | None, *, model: str | None = None) -> None:
        """Attach or update the OpenAI SDK client used by hybrid/llm evaluation."""
        self._llm_client = llm_client
        if model and model.strip():
            self._model = model.strip()

    def reset(self) -> ConversationState:
        """Reset conversation state and turn tracking to initial values."""
        self.state = _build_initial_state(self.config)
        self._processed_turns = []
        self._recent_turns = []
        return self.state

    def _evaluate_turn_llm(
        self, user_message: str
    ) -> tuple[int, list[str], str, bool] | None:
        """Evaluate free-form empathy/triggers with an LLM Judge (never sees gated secrets)."""
        if self._llm_client is None:
            return None

        tiers = self.config.information_tiers
        affect = self.config.affect_profile
        recent_block = (
            "\n".join(
                f"{'Student' if role == 'user' else 'Patient'}: {content}"
                for role, content in self._recent_turns[-_RECENT_TURNS_LIMIT:]
            )
            or "None yet."
        )
        eval_prompt = (
            "You are a fast evaluator scoring a medical student's latest utterance in a simulated patient interview.\n"
            "Return strictly valid JSON: "
            '{"trust_delta": <int -35..55>, "unlock_condition_met": <bool>, "reason": "<short reason>"}.\n'
            f"Patient cooperation level: {affect.cooperation_level}\n"
            f"Current trust_score (0-100): {self.state.trust_score} (unlock threshold: {self.state.unlock_threshold})\n"
            f"Unlock condition for sensitive personal topics: {tiers.unlock_condition or 'None'}\n"
            f"Rapport builders: {affect.rapport_builders}\n"
            f"Emotional triggers: {affect.emotional_triggers}\n"
            "Scoring rules:\n"
            "- Ordinary neutral clinical questions (symptoms, meds, smoking, duration) -> trust_delta: 0, unlock_condition_met: false.\n"
            "- Active emotional validation, genuine empathy, warmth, offering time/safety, or explaining why a question matters -> positive trust_delta (+15 to +55).\n"
            "- Set unlock_condition_met: true when the student clearly fulfills the unlock condition (e.g. genuine validation/empathy or warmly exploring worries/fears).\n"
            "- Lecturing, blaming, rushing, dismissing worries -> negative trust_delta (-15 to -35), unlock_condition_met: false.\n"
            f"Recent conversation context:\n{recent_block}"
        )

        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": eval_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_completion_tokens": 90,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        if _supports_reasoning_effort(self._model):
            request_kwargs["reasoning_effort"] = "none"

        try:
            response = self._llm_client.chat.completions.create(**request_kwargs)
            raw = response.choices[0].message.content or ""
            parsed = json.loads(_strip_json_fences(raw))
            delta = max(_MIN_NEGATIVE_DELTA, min(_MAX_POSITIVE_DELTA, int(parsed["trust_delta"])))
            unlock_met = bool(parsed.get("unlock_condition_met", False))
            reason = str(parsed.get("reason") or "LLM turn evaluation").strip()
            if unlock_met:
                signals = ["llm_judge_unlock"]
            elif delta > 0:
                signals = ["llm_judge_positive"]
            elif delta < 0:
                signals = ["llm_judge_negative"]
            else:
                signals = []
            return delta, signals, reason, unlock_met
        except Exception:
            return None

    def _select_evaluation(
        self, user_message: str
    ) -> tuple[int, list[str], str, bool, TransitionSource]:
        """Choose evaluation result according to heuristic / llm / hybrid mode."""
        h_delta, h_signals, h_reason = evaluate_student_turn_heuristic(user_message, self.config)
        has_secrets = bool(self.config.information_tiers.gated_secrets)
        trust_before = self.state.trust_score

        if self.evaluator_mode == "heuristic":
            return h_delta, h_signals, h_reason, False, "heuristic"

        if self.evaluator_mode == "llm":
            llm_result = self._evaluate_turn_llm(user_message)
            if llm_result is None:
                return h_delta, h_signals, h_reason, False, "heuristic"
            delta, signals, reason, unlock_met = llm_result
            return delta, signals, reason, unlock_met, "llm"

        # Hybrid mode: 0 ms fast-paths first, LLM Judge only when needed for free-form text.
        decisive_hit = bool(h_signals) and (
            trust_before + h_delta >= self.state.unlock_threshold or h_delta <= -20
        )
        if (
            decisive_hit
            or self._llm_client is None
            or not has_secrets
            or self.state.tier3_unlocked
            or _is_trivial_utterance(user_message)
        ):
            return h_delta, h_signals, h_reason, False, "heuristic"

        llm_result = self._evaluate_turn_llm(user_message)
        if llm_result is None:
            return h_delta, h_signals, h_reason, False, "heuristic"

        l_delta, l_signals, l_reason, l_unlock = llm_result
        if h_delta > 0 and l_delta > 0:
            merged_signals = list(dict.fromkeys([*h_signals, *l_signals]))
            if h_delta > l_delta:
                return h_delta, merged_signals, h_reason, l_unlock, "llm"
            return l_delta, merged_signals, l_reason, l_unlock, "llm"

        return l_delta, l_signals, l_reason, l_unlock, "llm"

    def process_student_turn(self, user_message: str) -> StateTransition:
        """Evaluate a student turn, update trust/stance, and check Tier 3 unlock."""
        delta, signals, reason, unlock_met_by_llm, source = self._select_evaluation(
            user_message
        )

        trust_before = self.state.trust_score
        trust_after = max(0, min(100, trust_before + delta))

        self.state.turn_count += 1
        self.state.trust_score = trust_after
        self.state.emotional_stance = _derive_stance(
            trust_after, self.state.unlock_threshold, delta
        )

        for signal in signals:
            if signal not in self.state.triggered_events:
                self.state.triggered_events.append(signal)

        newly_unlocked = False
        has_secrets = bool(self.config.information_tiers.gated_secrets)
        if (
            has_secrets
            and not self.state.tier3_unlocked
            and (trust_after >= self.state.unlock_threshold or unlock_met_by_llm)
        ):
            self.state.tier3_unlocked = True
            self.state.unlock_reason = reason
            newly_unlocked = True

        cleaned_user = user_message.strip()
        if cleaned_user:
            self._recent_turns.append(("user", cleaned_user))
            self._recent_turns = self._recent_turns[-_RECENT_TURNS_LIMIT:]

        transition = StateTransition(
            turn_number=self.state.turn_count,
            trust_delta=delta,
            trust_before=trust_before,
            trust_after=trust_after,
            newly_unlocked_tier3=newly_unlocked,
            source=source,
            signals=signals,
            reason=reason,
        )
        self.state.last_transition = transition
        return transition

    def record_patient_reply(self, assistant_message: str) -> list[str]:
        """Detect and record case facts likely disclosed in the patient's reply."""
        cleaned_reply = assistant_message.strip()
        if cleaned_reply:
            self._recent_turns.append(("assistant", cleaned_reply))
            self._recent_turns = self._recent_turns[-_RECENT_TURNS_LIMIT:]

        reply_tokens = _significant_tokens(assistant_message)
        if not reply_tokens:
            return []

        tiers = self.config.information_tiers
        candidates = list(tiers.spontaneous) + list(tiers.on_specific_query)
        if self.state.tier3_unlocked:
            candidates.extend(tiers.gated_secrets)

        newly_disclosed: list[str] = []
        for fact in candidates:
            if fact in self.state.disclosed_facts:
                continue
            fact_tokens = _significant_tokens(fact)
            if not fact_tokens:
                continue
            overlap = fact_tokens & reply_tokens
            ratio = len(overlap) / len(fact_tokens)
            if len(overlap) >= 2 and ratio >= 0.45:
                self.state.disclosed_facts.append(fact)
                newly_disclosed.append(fact)
        return newly_disclosed

    def sync_from_history(self, history: list[dict[str, str]]) -> ConversationState:
        """Synchronize state incrementally from a stateless chat history, resetting on new sessions."""
        turns: list[tuple[str, str]] = [
            (m["role"], m["content"].strip())
            for m in history
            if isinstance(m, dict)
            and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and m["content"].strip()
        ]

        processed_count = len(self._processed_turns)
        if turns[:processed_count] != self._processed_turns:
            self.reset()
            processed_count = 0

        for role, content in turns[processed_count:]:
            if role == "user":
                self.process_student_turn(content)
            else:
                self.record_patient_reply(content)
            self._processed_turns.append((role, content))

        return self.state

    def record_streamed_reply(self, reply_text: str) -> None:
        """Record a streamed assistant reply so the next sync recognizes it."""
        cleaned = reply_text.strip()
        if not cleaned:
            return
        self.record_patient_reply(cleaned)
        self._processed_turns.append(("assistant", cleaned))
