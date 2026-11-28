"""Voice server: lets ElevenLabs Agents use this engine as its "custom LLM".

ElevenLabs does speech-to-text, turn-taking and text-to-speech. On every patient
turn it calls ``POST /v1/chat/completions`` (OpenAI format, streamed) with the
full conversation so far. We ignore its system message, put our patient system
prompt (built from the case by ``prompt_builder``) in front, ask the OpenAI model
through ``ChatActorClient.stream_reply`` and stream the reply straight back.

Run (from engine/):
    uvicorn voice_server:app --host 127.0.0.1 --port 8787
ElevenLabs needs a public HTTPS URL, e.g. ``cloudflared tunnel --url http://127.0.0.1:8787``;
set the agent's custom LLM URL to ``https://<tunnel-host>/v1``.

Environment (engine/.env):
    OPENAI_API_KEY, OPENAI_MODEL, OPENAI_REASONING_EFFORT  - as for main.py
    PATIENT_CASE_PATH   case JSON (default: data/mock_gerhard_mueller.json)
    ENGINE_API_KEY      optional; if set, /v1/* requires "Authorization: Bearer <key>"
                        (store the same value as the agent's custom-LLM API key secret)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from case_adapter import load_patient_config
from llm_client import ChatActorClient, LLMClientError
from models import PatientConfig
from prompt_builder import build_system_prompt

load_dotenv()
log = logging.getLogger("voice_server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ENGINE_DATA_DIR = Path(__file__).resolve().parent / "data"
TEACHER_CASES_DIR = Path(__file__).resolve().parents[1] / "cases"
DEFAULT_CASE_PATH = ENGINE_DATA_DIR / "mock_gerhard_mueller.json"
FALLBACK_REPLY = "Sorry... could you say that again?"
# Requests that come through a Cloudflare tunnel carry these headers.
TUNNEL_HEADERS = ("cf-connecting-ip", "cf-ray")
# Routes reachable through the public tunnel (everything else is local/tailnet only).
PUBLIC_PATHS = {"/v1/chat/completions", "/v1/models", "/health"}


class PatientSession:
    """The loaded case, its system prompt and the OpenAI client."""

    def __init__(self, client_factory: Callable[[str], ChatActorClient] | None = None) -> None:
        self._client_factory = client_factory or (lambda prompt: ChatActorClient(prompt))
        self.case_path: Path | None = None
        self.config: PatientConfig | None = None
        self.client: ChatActorClient | None = None

    def load(self, source: Path | dict[str, Any]) -> None:
        """Load a case (engine format or teacher-UI format) from a path or a dict."""
        config = load_patient_config(source)
        prompt = build_system_prompt(config)
        self.client = self._client_factory(prompt)
        self.config = config
        self.case_path = source if isinstance(source, Path) else None
        log.info("loaded case %s (%s) with model %s", config.case_id, config.demographics.full_name, self.client.model)


def list_cases() -> list[dict[str, Any]]:
    """Cases from the teacher UI (cases/) and the engine's mock data (engine/data/)."""
    found = []
    for folder in (TEACHER_CASES_DIR, ENGINE_DATA_DIR):
        for path in sorted(folder.glob("*.json")):
            if path.name.endswith(".schema.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                config = load_patient_config(data)
            except Exception as exc:  # invalid or unrelated JSON: list it with the error
                found.append({"case_id": path.stem, "file": path.name, "error": str(exc)[:200]})
                continue
            demo = config.demographics
            found.append({"case_id": config.case_id, "file": path.name, "name": demo.full_name, "age": demo.age})
    return found


def find_case_file(case_id: str) -> Path | None:
    for folder in (TEACHER_CASES_DIR, ENGINE_DATA_DIR):
        for path in folder.glob("*.json"):
            if path.stem == case_id:
                return path
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("case_id") == case_id:
                    return path
            except (OSError, ValueError, AttributeError):
                continue
    return None


def talk_url() -> str | None:
    agent = (os.getenv("ELEVENLABS_AGENT_ID") or "").strip()
    return f"https://elevenlabs.io/app/talk-to?agent_id={agent}" if agent else None


def _case_path_from_env() -> Path:
    raw = (os.getenv("PATIENT_CASE_PATH") or "").strip()
    return Path(raw) if raw else DEFAULT_CASE_PATH


def create_app(session: PatientSession | None = None, *, load_case: bool = True) -> FastAPI:
    app = FastAPI(title="VIP voice server")
    app.state.session = session or PatientSession()
    if load_case:
        app.state.session.load(_case_path_from_env())

    @app.middleware("http")
    async def tunnel_guard(request: Request, call_next):
        via_tunnel = any(h in request.headers for h in TUNNEL_HEADERS)
        if via_tunnel and request.url.path not in PUBLIC_PATHS:
            return JSONResponse({"error": "not available through the public tunnel"}, status_code=403)
        key = (os.getenv("ENGINE_API_KEY") or "").strip()
        if key and request.url.path.startswith("/v1/"):
            if request.headers.get("authorization", "") != f"Bearer {key}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, Any]:
        s: PatientSession = app.state.session
        return {
            "ok": s.client is not None,
            "case_id": s.config.case_id if s.config else None,
            "model": s.client.model if s.client else None,
        }

    @app.get("/cases")
    def cases() -> dict[str, Any]:
        s: PatientSession = app.state.session
        return {"loaded": s.config.case_id if s.config else None, "cases": list_cases()}

    @app.post("/case")
    async def load_case_route(request: Request) -> dict[str, Any]:
        """Load the case to interview next: {"case_id": "case-003"} or {"case": {...}}.

        Local/tailnet only (blocked through the tunnel). ElevenLabs' next turn uses it.
        """
        body = await request.json()
        s: PatientSession = app.state.session
        try:
            if isinstance(body.get("case"), dict):
                s.load(body["case"])
            elif body.get("case_id"):
                path = find_case_file(str(body["case_id"]))
                if path is None:
                    raise HTTPException(404, f"case {body['case_id']!r} not found")
                s.load(path)
            else:
                raise HTTPException(400, 'send {"case_id": ...} or {"case": {...}}')
        except HTTPException:
            raise
        except Exception as exc:  # validation errors, bad JSON, LLM client setup
            raise HTTPException(422, f"could not load case: {exc}") from exc
        demo = s.config.demographics
        return {"case_id": s.config.case_id, "name": demo.full_name, "age": demo.age, "talk_url": talk_url()}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": "vip-patient", "object": "model", "owned_by": "vip"}]}

    @app.get("/prompt", response_class=PlainTextResponse)
    def prompt() -> str:
        s: PatientSession = app.state.session
        if s.client is None:
            raise HTTPException(503, "no case loaded")
        return s.client.system_prompt

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        s: PatientSession = app.state.session
        if s.client is None:
            raise HTTPException(503, "no case loaded")
        body = await request.json()
        history = [m for m in body.get("messages", []) if isinstance(m, dict)]
        stream = bool(body.get("stream"))
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        model_name = body.get("model") or "vip-patient"

        def reply_chunks() -> Iterator[str]:
            t0 = time.perf_counter()
            first = None
            parts: list[str] = []
            try:
                for piece in s.client.stream_reply(history):
                    if first is None:
                        first = time.perf_counter()
                    parts.append(piece)
                    yield piece
            except LLMClientError as exc:
                log.error("LLM error: %s", exc)
                if not parts:
                    parts.append(FALLBACK_REPLY)
                    yield FALLBACK_REPLY
            finally:
                end = time.perf_counter()
                ttft = (first - t0) * 1000 if first else None
                student = next((m.get("content") for m in reversed(history) if m.get("role") == "user"), "")
                log.info(
                    "turn: ttft=%s total=%.0fms | student: %.60s | patient: %.80s",
                    f"{ttft:.0f}ms" if ttft is not None else "-", (end - t0) * 1000, student, "".join(parts),
                )

        if not stream:
            text = "".join(reply_chunks())
            return {
                "id": completion_id, "object": "chat.completion", "created": created, "model": model_name,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            }

        def sse() -> Iterator[str]:
            def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
                payload = {
                    "id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                return f"data: {json.dumps(payload)}\n\n"

            yield chunk({"role": "assistant"})
            for piece in reply_chunks():
                yield chunk({"content": piece})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    return app


app = create_app() if os.getenv("VOICE_SERVER_NO_AUTOLOAD") != "1" else None
