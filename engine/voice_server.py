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
    PUBLIC_ACCESS_CODE  optional; if set, the teacher page (forwarded from TEACHER_UI_URL) and
                        the live patient video are reachable through the tunnel for anyone
                        who enters this code. Without it the tunnel serves ElevenLabs only.
    DIRECTOR, DIRECTOR_MODEL  per-turn face direction, see director.py
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from urllib.parse import parse_qs
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse

import eleven_agent
import key_check
import keystore
from case_adapter import load_patient_config
from director import EMOTIONS, MAX_INTENSITY, Director
from llm_client import DEFAULT_MODEL, ChatActorClient, LLMClientError
from models import PatientConfig
from prompt_builder import build_system_prompt

load_dotenv()
# The packaged app (VIP_APP=1) keeps the judge's own keys in the local key store.
APP_MODE = os.getenv("VIP_APP") == "1"
if APP_MODE:
    keystore.apply_to_environ()
log = logging.getLogger("voice_server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ENGINE_DATA_DIR = Path(__file__).resolve().parent / "data"
TEACHER_CASES_DIR = Path(__file__).resolve().parents[1] / "cases"
DEFAULT_CASE_PATH = ENGINE_DATA_DIR / "mock_gerhard_mueller.json"
FALLBACK_REPLY = "Sorry... could you say that again?"
# Requests that come through a Cloudflare tunnel carry these headers.
TUNNEL_HEADERS = ("cf-connecting-ip", "cf-ray")
# What the patient is doing in the conversation (Unreal's SetAttention, #37).
ATTENTION_STATES = {"listening", "thinking", "idle"}
# Routes ElevenLabs uses through the public tunnel (/v1/* also needs ENGINE_API_KEY).
PUBLIC_PATHS = {"/v1/chat/completions", "/v1/models", "/health"}
# Never through the tunnel, not even with the access code: the prompt holds the case's secrets.
PRIVATE_PATHS = {"/prompt", "/cases", "/case", "/director", "/turn"}
# Teacher routes of the forwarded page: they hold the diagnoses (the answer key), so testers who come
# through the tunnel get the student side only. (method, path); "*" matches every method.
TEACHER_ONLY_ROUTES = {
    ("*", "/api/cases"), ("*", "/api/case"), ("GET", "/api/practice-results"), ("*", "/api/grade"),
}
# The teacher page, forwarded for testers who come through the tunnel with the access code.
TEACHER_UI_URL = os.getenv("TEACHER_UI_URL", "http://127.0.0.1:8765").rstrip("/")
ACCESS_COOKIE = "vip_access"


def access_code() -> str:
    return (os.getenv("PUBLIC_ACCESS_CODE") or "").strip()


def access_token(code: str) -> str:
    """Cookie value for testers who entered the code (the code itself never goes in a cookie)."""
    return hmac.new(code.encode(), b"vip-access", hashlib.sha256).hexdigest()


def has_access(cookies: dict[str, str]) -> bool:
    code = access_code()
    return bool(code) and hmac.compare_digest(cookies.get(ACCESS_COOKIE, ""), access_token(code))


ACCESS_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>VIP · Access</title>
<style>body{{font:15px system-ui,sans-serif;background:#f5f8fa;color:#17252f;display:grid;place-items:center;min-height:100vh;margin:0}}
form{{background:#fff;padding:28px;border-radius:12px;box-shadow:0 2px 12px #0001;width:min(340px,90vw)}}
h1{{font-size:18px;margin:0 0 6px}}p{{color:#5b6b76;margin:0 0 16px}}input{{width:100%;box-sizing:border-box;padding:10px;border:1px solid #c9d4dc;border-radius:8px;font:inherit}}
button{{margin-top:12px;width:100%;padding:11px;border:0;border-radius:8px;background:#164e78;color:#fff;font:inherit;font-weight:600;cursor:pointer}}.err{{color:#b3261e}}</style></head>
<body><form method="post" action="/access"><h1>VIP · Virtual Interview Patient</h1><p>Enter the access code you were given.</p>
{error}<input name="code" type="password" autocomplete="current-password" autofocus aria-label="Access code"><button>Open</button></form></body></html>"""


class VideoViewer:
    """One browser watching the patient video. Keeps only the newest frame: a slow viewer skips frames."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.frame: bytes | None = None
        self.ready = asyncio.Event()

    def offer(self, frame: bytes) -> None:
        self.frame = frame
        self.ready.set()

    async def send_forever(self) -> None:
        while True:
            await self.ready.wait()
            self.ready.clear()
            if self.frame is not None:
                await self.ws.send_bytes(self.frame)


class StageHub:
    """Relays the patient's voice and emotion from the browser to Unreal (the MetaHuman).

    * ``/ws/unreal``: Unreal connects here and receives JSON messages
      ``{"type": "case", "case": {...}}`` (who the patient is and how they look, see ``case_look``),
      ``{"type": "emotion", "emotion": ..., "intensity": 0-2, "pain": 0-10, "discomfort": 0-1}``
      (pain and discomfort optional), ``{"type": "audio", "sample_rate": 16000, "pcm_b64": ...}``
      (mono 16-bit PCM), ``{"type": "state", "state": "listening|thinking|idle"}``,
      ``{"type": "interrupt"}`` and ``{"type": "viewers", "count": n}``. Unreal sends back binary
      JPEG frames of the patient while ``count`` > 0; they go to every browser on ``/ws/video``.
    * ``/ws/stage``: the teacher page connects here while a conversation runs and sends
      the patient's audio chunks from the ElevenLabs SDK. It is told how many Unreal
      clients listen, so it can mute its own playback while the MetaHuman speaks.
    """

    def __init__(self) -> None:
        self.unreal: set[WebSocket] = set()
        self.stages: set[WebSocket] = set()
        self.emotion: dict[str, Any] = {"type": "emotion", "emotion": "neutral", "intensity": 0.6}
        self.case: dict[str, Any] | None = None  # last case message, replayed when Unreal (re)connects
        self.viewers: set[VideoViewer] = set()
        self.frame: bytes | None = None  # newest JPEG of the patient from Unreal

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

    def push_frame(self, frame: bytes) -> None:
        self.frame = frame
        for viewer in self.viewers:
            viewer.offer(frame)

    async def viewers_changed(self) -> None:
        # Unreal only captures video while somebody watches
        await self.to_unreal({"type": "viewers", "count": len(self.viewers)})

    async def set_case(self, look: dict[str, Any] | None) -> None:
        self.case = {"type": "case", "case": look} if look else None
        self.frame = None  # the old patient's picture must not be shown for the new case
        if self.case:
            await self.to_unreal(self.case)

    async def set_state(self, state: str) -> None:
        if state in ATTENTION_STATES:
            await self.to_unreal({"type": "state", "state": state})

    async def set_emotion(
        self, emotion: str, intensity: float = 0.6, *, pain: float | None = None, discomfort: float | None = None,
    ) -> None:
        emotion = emotion if emotion in EMOTIONS else "neutral"
        message: dict[str, Any] = {
            "type": "emotion", "emotion": emotion, "intensity": max(0.0, min(MAX_INTENSITY, intensity)),
        }
        if pain is not None:
            message["pain"] = max(0.0, min(10.0, pain))
        if discomfort is not None:
            message["discomfort"] = max(0.0, min(1.0, discomfort))
        self.emotion = message
        await self.to_unreal(message)


class PatientSession:
    """The loaded case, its system prompt and the OpenAI client."""

    def __init__(
        self, client_factory: Callable[[str], ChatActorClient] | None = None, director: Director | None = None,
    ) -> None:
        self._client_factory = client_factory or (lambda prompt: ChatActorClient(prompt))
        self.case_path: Path | None = None
        self.source: Path | dict[str, Any] | None = None
        self.config: PatientConfig | None = None
        self.client: ChatActorClient | None = None
        self.mood = "neutral"
        self.case_data: dict[str, Any] | None = None  # the full case, server side only (the director reads it)
        self.look: dict[str, Any] | None = None  # what Unreal needs to show this patient
        self.director = director if director is not None else (Director() if Director.enabled() else None)

    def load(self, source: Path | dict[str, Any]) -> None:
        """Load a case (engine format or teacher-UI format) from a path or a dict."""
        self.source = source
        data = source if isinstance(source, dict) else json.loads(Path(source).read_text(encoding="utf-8"))
        config = load_patient_config(data)
        self.mood = str((data.get("personality") or {}).get("mood") or "neutral")
        self.case_data = data
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


async def direct_face(session: PatientSession, hub: StageHub, history: list[dict[str, Any]]) -> None:
    """Ask the director how the face reacts to this turn and send it to Unreal."""
    if session.director is None:
        return
    t0 = time.perf_counter()
    direction = await asyncio.to_thread(session.director.direct, session.case_data, history)
    if direction is None:
        return
    await hub.set_emotion(
        direction["emotion"], direction["intensity"], pain=direction["pain"], discomfort=direction["discomfort"],
    )
    log.info(
        "face: %s %.2f pain=%.1f discomfort=%.2f (%.0fms)", direction["emotion"], direction["intensity"],
        direction["pain"], direction["discomfort"], (time.perf_counter() - t0) * 1000,
    )


def create_app(session: PatientSession | None = None, *, load_case: bool = True) -> FastAPI:
    app = FastAPI(title="VIP voice server")
    app.state.session = session or PatientSession()
    app.state.stage = StageHub()
    app.state.director_tasks = set()  # keeps running director calls referenced
    if load_case:
        try:
            app.state.session.load(_case_path_from_env())
        except LLMClientError as exc:
            if not APP_MODE:
                raise
            # First start of the app: no keys yet, the key screen asks for them
            app.state.session.source = _case_path_from_env()
            log.info("waiting for API keys: %s", exc)

    def _is_local(request: Request) -> bool:
        return request.client is not None and request.client.host in ("127.0.0.1", "::1", "testclient")

    def start_direction(history: list[dict[str, Any]]) -> None:
        """Run the director next to the reply (never delaying it)."""
        s: PatientSession = app.state.session
        if s.director is None:
            return
        task = asyncio.create_task(direct_face(s, app.state.stage, history))
        app.state.director_tasks.add(task)
        task.add_done_callback(app.state.director_tasks.discard)

    @app.post("/director")
    async def director_route(request: Request) -> dict[str, Any]:
        """The page reports a finished student turn: {"messages": [...]}. Local only.

        Used when ElevenLabs talks to OpenAI directly (the desktop app), so /v1/chat/completions
        never runs: the patient still thinks and the face still follows the conversation.
        """
        if not _is_local(request):
            raise HTTPException(403, "local only")
        body = await request.json()
        history = [m for m in body.get("messages", []) if isinstance(m, dict)]
        await app.state.stage.set_state("thinking")
        start_direction(history)
        return {"ok": True, "director": app.state.session.director is not None}

    @app.post("/turn")
    async def typed_turn(request: Request) -> dict[str, Any]:
        """A typed student turn (no voice available): {"messages": [...]} -> {"reply": ...}. Local only."""
        if not _is_local(request):
            raise HTTPException(403, "local only")
        s: PatientSession = app.state.session
        if s.client is None:
            raise HTTPException(503, "no case loaded")
        body = await request.json()
        history = [
            {"role": m["role"], "content": m["content"]} for m in body.get("messages", [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
        ]
        await app.state.stage.set_state("thinking")
        start_direction(history)
        try:
            reply = await asyncio.to_thread(lambda: "".join(s.client.stream_reply(history)))
        except LLMClientError as exc:
            log.error("LLM error: %s", exc)
            reply = ""
        await app.state.stage.set_state("listening")
        return {"reply": reply.strip() or FALLBACK_REPLY}

    def _key_status() -> dict[str, Any]:
        s: PatientSession = app.state.session
        return {
            "app": APP_MODE,
            "openai": bool(os.getenv("OPENAI_API_KEY")),
            "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
            "agent": bool(os.getenv("ELEVENLABS_AGENT_ID")),
            "model": os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
            "ready": s.client is not None,
        }

    def _push_prompt() -> str | None:
        """Write the loaded case's prompt into the judge's ElevenLabs agent. Returns an error or None."""
        s: PatientSession = app.state.session
        key, agent = os.getenv("ELEVENLABS_API_KEY"), os.getenv("ELEVENLABS_AGENT_ID")
        if not (key and agent and s.client):
            return None
        try:
            eleven_agent.set_prompt(key, agent, s.client.system_prompt)
        except eleven_agent.ElevenLabsError as exc:
            log.error("could not update the agent prompt: %s", exc)
            return str(exc)
        return None

    @app.get("/keys")
    def keys_status(request: Request) -> dict[str, Any]:
        """Which keys the app has (never the values). Local only."""
        if not _is_local(request):
            raise HTTPException(403, "local only")
        return _key_status()

    @app.post("/keys")
    async def keys_save(request: Request) -> dict[str, Any]:
        """Check and store the judge's keys: {"openai_key": ..., "elevenlabs_key": ...}. Local only.

        Keys left empty keep their stored value. Nothing is stored if a given key fails its check.
        """
        if not _is_local(request):
            raise HTTPException(403, "local only")
        body = await request.json()
        openai_key = str(body.get("openai_key") or "").strip()
        eleven_key = str(body.get("elevenlabs_key") or "").strip()
        model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
        checks: dict[str, Any] = {}
        if openai_key:
            checks["openai"] = key_check.check_openai(openai_key, model)
        if eleven_key:
            checks["elevenlabs"] = key_check.check_elevenlabs(eleven_key)
        failed = {name: c["error"] for name, c in checks.items() if not c["ok"]}
        if failed:
            raise HTTPException(422, {"errors": failed})

        changes = {}
        if openai_key:
            changes["OPENAI_API_KEY"] = openai_key
        if eleven_key:
            changes["ELEVENLABS_API_KEY"] = eleven_key
        if changes:
            if APP_MODE:
                keystore.save(changes)
            os.environ.update(changes)

        result: dict[str, Any] = {"checks": checks}
        el_key, oa_key = os.getenv("ELEVENLABS_API_KEY"), os.getenv("OPENAI_API_KEY")
        if el_key and oa_key and (changes or not os.getenv("ELEVENLABS_AGENT_ID")):
            # A new OpenAI key needs a new secret, so set the agent up again then
            reuse = None if openai_key else os.getenv("ELEVENLABS_AGENT_ID")
            try:
                agent_id = eleven_agent.ensure_agent(el_key, oa_key, model, reuse)
                os.environ["ELEVENLABS_AGENT_ID"] = agent_id
                if APP_MODE:
                    keystore.save({"ELEVENLABS_AGENT_ID": agent_id})
            except eleven_agent.ElevenLabsError as exc:
                log.error("ElevenLabs agent setup failed: %s", exc)
                result["voice_error"] = str(exc)

        s: PatientSession = app.state.session
        if oa_key and s.source is not None:
            try:
                s.load(s.source)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(422, f"keys saved, but the case could not be loaded: {exc}") from exc
            error = _push_prompt()
            if error:
                result.setdefault("voice_error", error)
        result.update(_key_status())
        return result

    @app.delete("/keys")
    def keys_forget(request: Request) -> dict[str, Any]:
        """Forget the stored keys on this computer. Local only."""
        if not _is_local(request):
            raise HTTPException(403, "local only")
        if APP_MODE:
            keystore.clear()
        for name in keystore.KEY_NAMES:
            os.environ.pop(name, None)
        app.state.session.client = None
        return _key_status()

    @app.get("/signed-url")
    def get_signed_url(request: Request) -> dict[str, Any]:
        """A fresh conversation link for the judge's ElevenLabs agent. Local only."""
        if not _is_local(request):
            raise HTTPException(403, "local only")
        key, agent = os.getenv("ELEVENLABS_API_KEY"), os.getenv("ELEVENLABS_AGENT_ID")
        if not (key and agent):
            raise HTTPException(409, "add an ElevenLabs key first")
        try:
            return {"signed_url": eleven_agent.signed_url(key, agent)}
        except eleven_agent.ElevenLabsError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.middleware("http")
    async def tunnel_guard(request: Request, call_next):
        via_tunnel = any(h in request.headers for h in TUNNEL_HEADERS)
        path = request.url.path
        if via_tunnel and path not in PUBLIC_PATHS:
            # Testers: the teacher page, after entering PUBLIC_ACCESS_CODE. Never the private routes.
            teacher_only = ("*", path) in TEACHER_ONLY_ROUTES or (request.method, path) in TEACHER_ONLY_ROUTES
            if path in PRIVATE_PATHS or teacher_only or not access_code():
                return JSONResponse({"error": "not available through the public tunnel"}, status_code=403)
            if path != "/access" and not has_access(request.cookies):
                if request.method == "GET":
                    return RedirectResponse("/access", status_code=303)
                return JSONResponse({"error": "enter the access code first"}, status_code=401)
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
        # The MetaHuman switches to this patient's face and look, then starts with the case's mood
        await app.state.stage.set_case(s.look)
        await app.state.stage.set_emotion(s.mood)
        result = {
            "case_id": s.config.case_id, "name": demo.full_name, "age": demo.age, "mood": s.mood,
            "agent_id": (os.getenv("ELEVENLABS_AGENT_ID") or "").strip() or None, "talk_url": talk_url(),
        }
        if APP_MODE:
            # The app's agent lives in the judge's account and calls OpenAI directly: give it this case
            error = _push_prompt()
            result["signed"] = True
            result["talk_url"] = None
            if error:
                result["voice_error"] = error
        return result

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
        await ws.send_text(json.dumps({"type": "viewers", "count": len(hub.viewers)}))
        await hub.status()
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes"):  # a JPEG frame of the patient
                    hub.push_frame(message["bytes"])
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
        if _via_tunnel(ws) and not has_access(ws.cookies):
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
                        # false: lips only; the voice plays in the tester's browser, not on the demo computer
                        "audible": bool(message.get("audible", True)),
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

    @app.websocket("/ws/video")
    async def video_socket(ws: WebSocket) -> None:
        """Browsers watch the patient here: binary JPEG frames from Unreal, newest first."""
        hub: StageHub = app.state.stage
        if _via_tunnel(ws) and not has_access(ws.cookies):
            await ws.close(code=1008)
            return
        await ws.accept()
        viewer = VideoViewer(ws)
        hub.viewers.add(viewer)
        await hub.viewers_changed()
        if hub.frame:
            viewer.offer(hub.frame)
        sender = asyncio.create_task(viewer.send_forever())
        try:
            while True:
                await ws.receive_text()  # nothing expected; notices when the viewer leaves
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            hub.viewers.discard(viewer)
            await hub.viewers_changed()

    @app.get("/access", response_class=HTMLResponse)
    def access_form() -> str:
        return ACCESS_PAGE.format(error="")

    @app.post("/access")
    async def access_check(request: Request):
        code = (parse_qs((await request.body()).decode("utf-8", "replace")).get("code") or [""])[0].strip()
        expected = access_code()
        if not expected or not hmac.compare_digest(code.encode(), expected.encode()):
            return HTMLResponse(ACCESS_PAGE.format(error='<p class="err">That code is not right.</p>'), status_code=401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(ACCESS_COOKIE, access_token(expected), max_age=7 * 24 * 3600,
                            httponly=True, secure=True, samesite="lax")
        return response

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
        # The student has finished a turn: the patient thinks until the voice arrives,
        # and the director decides the face for the answer (next to the reply, never delaying it)
        await app.state.stage.set_state("thinking")
        start_direction(history)
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

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST"], include_in_schema=False)
    async def teacher_page(path: str, request: Request) -> Response:
        """Everything else is the teacher page (for testers coming through the tunnel)."""
        transport = getattr(app.state, "teacher_transport", None)  # tests inject a fake
        async with httpx.AsyncClient(transport=transport, timeout=60) as client:
            try:
                upstream = await client.request(
                    request.method, f"{TEACHER_UI_URL}/{path}", params=request.query_params,
                    content=await request.body(), headers={"content-type": request.headers.get("content-type", "")},
                )
            except httpx.HTTPError:
                return JSONResponse({"error": "the teacher page is not running"}, status_code=502)
        keep = {"content-type", "cache-control", "last-modified"}
        return Response(upstream.content, status_code=upstream.status_code,
                        headers={k: v for k, v in upstream.headers.items() if k.lower() in keep})

    return app


app = create_app() if os.getenv("VOICE_SERVER_NO_AUTOLOAD") != "1" else None
