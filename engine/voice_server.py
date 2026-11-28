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
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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
ATTENTION_STATES = {"listening", "thinking", "idle"}
PUBLIC_PATHS = {"/v1/chat/completions", "/v1/models", "/health"}
# Shared emotion names (README, Unreal's SetEmotion); unknown values become neutral.
EMOTIONS = {"neutral", "happy", "sad", "fear", "disgust", "anger", "surprise"}


class StageHub:
    """Relays the patient's voice and emotion from the browser to Unreal (the MetaHuman).

    * ``/ws/unreal``: Unreal connects here and receives JSON messages
      ``{"type": "case", "case": {...}}`` (who the patient is: picks the face),
      ``{"type": "emotion", "emotion": ..., "intensity": ...}``,
      ``{"type": "audio", "sample_rate": 16000, "pcm_b64": ...}`` (mono 16-bit PCM),
      ``{"type": "state", "state": "listening|thinking|idle"}`` and ``{"type": "interrupt"}``.
    * ``/ws/stage``: the teacher page connects here while a conversation runs and sends
      the patient's audio chunks from the ElevenLabs SDK. It is told how many Unreal
      clients listen, so it can mute its own playback while the MetaHuman speaks.
    """

    def __init__(self) -> None:
        self.unreal: set[WebSocket] = set()
        self.stages: set[WebSocket] = set()
        self.emotion = {"type": "emotion", "emotion": "neutral", "intensity": 0.6}
        self.case: dict[str, Any] | None = None  # last case message, replayed when Unreal (re)connects

    async def to_unreal(self, message: dict[str, Any]) -> None:
        text = json.dumps(message)
        for ws in list(self.unreal):
            try:
                await ws.send_text(text)
            except Exception:  # closed socket: forget it
                self.unreal.discard(ws)

    async def status(self) -> None:
        text = json.dumps({"type": "status", "unreal": len(self.unreal)})
        for ws in list(self.stages):
            try:
                await ws.send_text(text)
            except Exception:
                self.stages.discard(ws)

    async def set_case(self, case: dict[str, Any] | None) -> None:
        self.case = {"type": "case", "case": case} if case else None
        if self.case:
            await self.to_unreal(self.case)

    async def set_state(self, state: str) -> None:
        if state in ATTENTION_STATES:
            await self.to_unreal({"type": "state", "state": state})

    async def set_emotion(self, emotion: str, intensity: float = 0.6) -> None:
        emotion = emotion if emotion in EMOTIONS else "neutral"
        self.emotion = {"type": "emotion", "emotion": emotion, "intensity": max(0.0, min(1.0, intensity))}
        await self.to_unreal(self.emotion)


class PatientSession:
    """The loaded case, its system prompt and the OpenAI client."""

    def __init__(self, client_factory: Callable[[str], ChatActorClient] | None = None) -> None:
        self._client_factory = client_factory or (lambda prompt: ChatActorClient(prompt))
        self.case_path: Path | None = None
        self.config: PatientConfig | None = None
        self.client: ChatActorClient | None = None
        self.mood = "neutral"
        self.look: dict[str, Any] | None = None  # what Unreal needs to show this patient

    def load(self, source: Path | dict[str, Any]) -> None:
        """Load a case (engine format or teacher-UI format) from a path or a dict."""
        data = source if isinstance(source, dict) else json.loads(Path(source).read_text(encoding="utf-8"))
        config = load_patient_config(data)
        self.mood = str((data.get("personality") or {}).get("mood") or "neutral")
        self.look = case_look(data)
        prompt = build_system_prompt(config)
        self.client = self._client_factory(prompt)
        self.config = config
        self.case_path = source if isinstance(source, Path) else None
        log.info("loaded case %s (%s) with model %s", config.case_id, config.demographics.full_name, self.client.model)


def case_look(data: dict[str, Any]) -> dict[str, Any] | None:
    """The part of a teacher case that Unreal uses to show the patient (VIPCase.cpp).

    Only appearance and behaviour: the diagnosis, the facts and the secrets stay here.
    Engine-format cases have no look, so Unreal keeps its default patient.
    """
    if "schema_version" not in data:
        return None
    patient = data.get("patient") or {}
    look: dict[str, Any] = {
        "case_id": data.get("case_id"),
        "character_id": data.get("character_id"),
        "patient": {k: patient[k] for k in ("name", "age", "gender") if k in patient},
        "personality": {k: v for k, v in (data.get("personality") or {}).items() if k in ("type", "mood")},
    }
    if isinstance(data.get("presentation"), dict):
        look["presentation"] = data["presentation"]
    return look


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
    app.state.stage = StageHub()
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
        # The MetaHuman switches to this patient's face and starts with the case's mood
        await app.state.stage.set_case(s.look)
        await app.state.stage.set_emotion(s.mood)
        return {
            "case_id": s.config.case_id, "name": demo.full_name, "age": demo.age, "mood": s.mood,
            "agent_id": (os.getenv("ELEVENLABS_AGENT_ID") or "").strip() or None, "talk_url": talk_url(),
        }

    def _via_tunnel(ws: WebSocket) -> bool:
        return any(h in ws.headers for h in TUNNEL_HEADERS)

    @app.websocket("/ws/unreal")
    async def unreal_socket(ws: WebSocket) -> None:
        """Unreal (MetaHuman) receives the patient's emotion and voice here. Local/tailnet only."""
        hub: StageHub = app.state.stage
        if _via_tunnel(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        hub.unreal.add(ws)
        log.info("unreal connected (%d)", len(hub.unreal))
        if hub.case:
            await ws.send_text(json.dumps(hub.case))
        await ws.send_text(json.dumps(hub.emotion))
        await hub.status()
        try:
            while True:
                await ws.receive_text()  # nothing expected from Unreal; keeps the socket open
        except WebSocketDisconnect:
            pass
        finally:
            hub.unreal.discard(ws)
            log.info("unreal disconnected (%d)", len(hub.unreal))
            await hub.status()

    @app.websocket("/ws/stage")
    async def stage_socket(ws: WebSocket) -> None:
        """The teacher page sends the patient's audio here during a conversation."""
        hub: StageHub = app.state.stage
        if _via_tunnel(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        hub.stages.add(ws)
        await ws.send_text(json.dumps({"type": "status", "unreal": len(hub.unreal)}))
        try:
            while True:
                message = json.loads(await ws.receive_text())
                kind = message.get("type")
                if kind == "audio" and isinstance(message.get("pcm_b64"), str):
                    await hub.to_unreal({
                        "type": "audio",
                        "sample_rate": int(message.get("sample_rate") or 16000),
                        "pcm_b64": message["pcm_b64"],
                    })
                elif kind == "emotion":
                    await hub.set_emotion(str(message.get("emotion", "neutral")), float(message.get("intensity", 0.6)))
                elif kind == "interrupt":
                    await hub.to_unreal({"type": "interrupt"})
                elif kind == "state":
                    await hub.set_state(str(message.get("state", "")))
        except (WebSocketDisconnect, ValueError, json.JSONDecodeError):
            pass
        finally:
            hub.stages.discard(ws)

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
        # The student has finished a turn: the patient thinks until the voice arrives
        await app.state.stage.set_state("thinking")
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
