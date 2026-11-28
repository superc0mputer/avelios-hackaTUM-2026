"""Interactive CLI test runner for the simulated patient actor."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from case_adapter import load_patient_config
from llm_client import ChatActorClient, DEFAULT_MODEL, LLMClientError
from models import PatientConfig
from prompt_builder import build_system_prompt
from state_manager import StateManager

DEFAULT_CASE_PATH = Path(__file__).resolve().parent / "data" / "mock_gerhard_mueller.json"


def resolve_case_path(cli_case: str | None) -> Path:
    """Resolve case JSON path with precedence: CLI argument > env var > default."""
    if cli_case and cli_case.strip():
        return Path(cli_case.strip())
    env_case = os.getenv("PATIENT_CASE_PATH")
    if env_case and env_case.strip():
        return Path(env_case.strip())
    return DEFAULT_CASE_PATH


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for the interactive test runner."""
    parser = argparse.ArgumentParser(
        description="Interactive CLI test runner for the simulated patient training app."
    )
    parser.add_argument(
        "-c",
        "--case",
        help="Path to a PatientConfig JSON file (overrides PATIENT_CASE_PATH).",
    )
    parser.add_argument(
        "-m",
        "--model",
        help="OpenAI model name (overrides OPENAI_MODEL).",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the generated system prompt for the selected case and exit.",
    )
    parser.add_argument(
        "--debug-state",
        action="store_true",
        help="Print trust, emotional stance, and Tier 3 gating transitions after each turn.",
    )
    return parser.parse_args(argv)


class CLIRunner:
    """Handles slash commands and live conversation turns in the terminal."""

    def __init__(
        self,
        config: PatientConfig,
        system_prompt: str,
        client: ChatActorClient | None = None,
        client_error: str | None = None,
        output_fn: Callable[[str], None] = print,
        state_manager: StateManager | None = None,
        debug_state: bool = False,
    ) -> None:
        self.config = config
        self.system_prompt = system_prompt
        self.client = client
        self.client_error = client_error
        self._out = output_fn
        self.state_manager = state_manager or StateManager(config)
        self.debug_state = debug_state

    def print_header(self) -> None:
        """Display loaded case metadata and available slash commands."""
        demo = self.config.demographics
        active_model = self.client.model if self.client else (os.getenv("OPENAI_MODEL") or DEFAULT_MODEL)
        self._out("=" * 68)
        self._out(f"Case:    {self.config.case_title} [{self.config.case_id}]")
        self._out(f"Patient: {demo.full_name}, {demo.age} ({demo.occupation})")
        self._out(f"Setting: {self.config.clinical_setting}")
        self._out(f"Model:   {active_model}")
        self._out("Commands: /prompt  /config  /state  /reset  /help  /quit")
        self._out("=" * 68)
        if self.client_error:
            self._out(f"[Notice] LLM chat unavailable: {self.client_error}")
            self._out("         Inspection commands (/prompt, /config, /state, /reset, /help, /quit) still work.")

    def print_help(self) -> None:
        """Display supported slash commands."""
        self._out(
            "Available commands:\n"
            "  /prompt  Show the generated system prompt\n"
            "  /config  Show the loaded PatientConfig JSON\n"
            "  /state   Show the live conversation state and Tier 3 lock status\n"
            "  /reset   Reset the conversation history and state\n"
            "  /help    Show this help message\n"
            "  /quit    Exit the test runner (alias: /exit)"
        )

    def handle_input(self, raw_input: str) -> bool:
        """Process a single line of user input. Returns False when the loop should exit."""
        text = raw_input.strip()
        if not text:
            return True

        if text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd in {"/quit", "/exit"}:
                self._out("Ending session.")
                return False
            if cmd == "/prompt":
                self._out("\n--- Generated System Prompt ---")
                self._out(self.system_prompt)
                self._out("--- End of System Prompt ---\n")
                return True
            if cmd == "/config":
                self._out("\n--- Loaded PatientConfig JSON ---")
                self._out(self.config.model_dump_json(indent=2))
                self._out("--- End of PatientConfig JSON ---\n")
                return True
            if cmd == "/state":
                self._out("\n--- Live Conversation State ---")
                self._out(self.state_manager.state.model_dump_json(indent=2))
                self._out("--- End of Conversation State ---\n")
                return True
            if cmd == "/reset":
                self.state_manager.reset()
                self.system_prompt = build_system_prompt(self.config, state=self.state_manager.state)
                if self.client is not None:
                    self.client.reset(self.system_prompt)
                self._out("Conversation history and state reset.")
                return True
            if cmd == "/help":
                self.print_help()
                return True

            self._out(f"Unknown command: {cmd}. Type /help for available commands.")
            return True

        if self.client is None:
            reason = self.client_error or "Chat client is not configured."
            self._out(f"[Error] {reason}")
            return True

        transition = self.state_manager.process_student_turn(text)
        self.system_prompt = build_system_prompt(self.config, state=self.state_manager.state)

        try:
            reply = self.client.send_message(text, system_prompt=self.system_prompt)
        except LLMClientError as exc:
            self._out(f"[Error] {exc}")
            return True

        self.state_manager.record_patient_reply(reply)
        self._out(f"{self.config.demographics.full_name}: {reply}")
        if self.debug_state:
            s = self.state_manager.state
            unlock_tag = " [TIER 3 UNLOCKED]" if transition.newly_unlocked_tier3 else ""
            signals = ", ".join(transition.signals) if transition.signals else "none"
            self._out(
                f"[State] turn={s.turn_count} trust={s.trust_score}/{s.unlock_threshold} "
                f"({transition.trust_delta:+d}) eval={transition.source} stance={s.emotional_stance} "
                f"tier3={'unlocked' if s.tier3_unlocked else 'locked'} signals=[{signals}]{unlock_tag}"
            )
        return True

    def run(self, input_fn: Callable[[str], str] = input) -> None:
        """Run the interactive REPL loop until exit or EOF."""
        self.print_header()
        while True:
            try:
                user_line = input_fn("\nStudent> ")
            except (EOFError, KeyboardInterrupt):
                self._out("\nEnding session.")
                break

            if not self.handle_input(user_line):
                break


def main(argv: list[str] | None = None) -> int:
    """Entry point for the simulated patient CLI test runner."""
    load_dotenv()
    args = parse_args(argv)
    case_path = resolve_case_path(args.case)

    try:
        config = load_patient_config(case_path)
    except FileNotFoundError:
        print(f"Error: Case file not found: {case_path}", file=sys.stderr)
        return 1
    except (OSError, ValidationError, ValueError, KeyError) as exc:
        print(f"Error: Failed to load case file {case_path}: {exc}", file=sys.stderr)
        return 1

    state_manager = StateManager(config)
    system_prompt = build_system_prompt(config, state=state_manager.state)

    if args.show_prompt:
        print(system_prompt)
        return 0

    client: ChatActorClient | None = None
    client_error: str | None = None
    try:
        client = ChatActorClient(system_prompt, model=args.model)
    except LLMClientError as exc:
        client_error = str(exc)

    if client is not None and isinstance(client.raw_client, OpenAI):
        state_manager.set_llm_client(
            client.raw_client,
            model=os.getenv("OPENAI_STATE_MODEL") or client.model,
        )

    runner = CLIRunner(
        config=config,
        system_prompt=system_prompt,
        client=client,
        client_error=client_error,
        state_manager=state_manager,
        debug_state=args.debug_state,
    )
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
