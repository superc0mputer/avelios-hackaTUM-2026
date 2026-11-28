"""OpenAI voice route: a second way to talk to the patient, next to ElevenLabs Agents.

The teacher page records one student utterance at a time (it detects speech and
silence itself) and sends it over ``/ws/talk``. For each utterance we

1. transcribe it with OpenAI speech-to-text,
2. let the patient engine answer (same system prompt as the ElevenLabs route),
3. speak the answer sentence by sentence with OpenAI text-to-speech, steered by the
   case (age, gender, mood, pain), and
4. stream the audio (mono 16-bit PCM, 24 kHz) to Unreal, or back to the page when no
   MetaHuman is connected.

No public tunnel is needed: everything runs between the page, this server and OpenAI.

Environment (engine/.env), all optional except OPENAI_API_KEY:
    OPENAI_STT_MODEL   speech-to-text model (default gpt-4o-mini-transcribe)
    OPENAI_TTS_MODEL   text-to-speech model (default gpt-4o-mini-tts)
    OPENAI_TTS_VOICE   force one voice; otherwise chosen from the patient's gender
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from models import PatientConfig

log = logging.getLogger("openai_voice")

DEFAULT_STT_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
TTS_SAMPLE_RATE = 24000  # OpenAI's "pcm" format: 24 kHz, mono, 16-bit little endian
CHUNK_BYTES = TTS_SAMPLE_RATE * 2 // 10  # 0.1 s of audio per message
VOICES = {"male": "ash", "female": "coral"}
DEFAULT_VOICE = "sage"
# A sentence ends at . ! ? or … followed by a space; very short pieces wait for more text.
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
MIN_SENTENCE_CHARS = 25

MOOD_TONE = {
    "neutral": "calm and matter-of-fact",
    "happy": "warm and relieved",
    "sad": "low, tired and a little flat",
    "fear": "worried and tense, slightly faster",
    "anger": "irritated and curt",
    "disgust": "put off and reluctant",
    "surprise": "surprised",
    "anxious": "worried and tense, slightly faster",
}


def stt_model() -> str:
    return (os.getenv("OPENAI_STT_MODEL") or DEFAULT_STT_MODEL).strip()


def tts_model() -> str:
    return (os.getenv("OPENAI_TTS_MODEL") or DEFAULT_TTS_MODEL).strip()


def choose_voice(config: PatientConfig | None) -> str:
    forced = (os.getenv("OPENAI_TTS_VOICE") or "").strip()
    if forced:
        return forced
    gender = (config.demographics.gender if config else "").strip().lower()
    return VOICES.get(gender, DEFAULT_VOICE)


def voice_instructions(config: PatientConfig | None, mood: str = "neutral") -> str:
    """How the patient should sound, for the TTS model's ``instructions`` field."""
    if config is None:
        return "Speak like a patient talking to a doctor: natural, conversational, not like a narrator."
    demo = config.demographics
    affect = config.affect_profile
    tone = MOOD_TONE.get(mood.lower(), MOOD_TONE.get(affect.baseline_mood.lower(), "natural"))
    lines = [
        f"You are the voice of {demo.full_name}, a {demo.age}-year-old {demo.gender} patient "
        "talking to a doctor in a consultation. Sound like a real person, not a narrator or an assistant.",
        f"Tone: {tone}. Communication style: {affect.communication_style}.",
        "Use natural pauses and everyday intonation; keep it understated.",
    ]
    if demo.age >= 70:
        lines.append("The voice is that of an older person: a little slower and softer.")
    if affect.pain_level is not None and affect.pain_level >= 4:
        lines.append(f"The patient is in pain ({affect.pain_level}/10): strained, with small breaks in the voice.")
    return " ".join(lines)


LANGUAGE_CODES = {"english": "en", "german": "de", "deutsch": "de", "french": "fr", "spanish": "es", "italian": "it"}


def language_code(language: str | None) -> str | None:
    """ISO 639-1 code for speech-to-text ("English", "en-US" -> "en"); None if unknown."""
    raw = (language or "").strip().lower()
    if raw in LANGUAGE_CODES:
        return LANGUAGE_CODES[raw]
    code = raw.split("-")[0].split("_")[0]
    return code if len(code) == 2 and code.isalpha() else None


def split_sentences(buffer: str, final: bool = False) -> tuple[list[str], str]:
    """Cut complete sentences off the front of ``buffer``; return them and the rest."""
    parts = SENTENCE_END.split(buffer)
    rest = parts.pop() if parts else ""
    ready: list[str] = []
    pending = ""
    for part in parts:
        pending = f"{pending} {part}".strip()
        if len(pending) >= MIN_SENTENCE_CHARS:
            ready.append(pending)
            pending = ""
    rest = f"{pending} {rest}".strip()
    if final and rest:
        ready.append(rest)
        rest = ""
    return ready, rest


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap mono 16-bit PCM in a WAV header (the page sends raw PCM)."""
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return out.getvalue()


class OpenAIVoice:
    """Speech-to-text and text-to-speech through the OpenAI API (async client)."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from openai import AsyncOpenAI

            base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
            client = AsyncOpenAI(api_key=(os.getenv("OPENAI_API_KEY") or "").strip(), base_url=base_url)
        self.client = client

    async def transcribe(self, wav: bytes, language: str | None = None) -> str:
        kwargs: dict[str, Any] = {"model": stt_model(), "file": ("utterance.wav", wav, "audio/wav")}
        if language:
            kwargs["language"] = language
        result = await self.client.audio.transcriptions.create(**kwargs)
        return (getattr(result, "text", "") or "").strip()

    async def speak(self, text: str, voice: str, instructions: str):
        """Yield raw PCM bytes (24 kHz mono 16-bit) as they arrive."""
        async with self.client.audio.speech.with_streaming_response.create(
            model=tts_model(), voice=voice, input=text, instructions=instructions, response_format="pcm",
        ) as response:
            async for chunk in response.iter_bytes():
                if chunk:
                    yield chunk


class TalkSession:
    """One conversation over ``/ws/talk``: history, the running reply, and timing.

    ``send_page`` sends a JSON message to the page; ``hub`` relays to Unreal.
    """

    def __init__(self, session: Any, hub: Any, voice: OpenAIVoice, send_page: Callable[[dict], Any]) -> None:
        self.session = session
        self.hub = hub
        self.voice = voice
        self.send_page = send_page
        self.history: list[dict[str, str]] = []
        self.reply_task: asyncio.Task | None = None
        self.cancelled = threading.Event()

    async def state(self, state: str) -> None:
        """Tell Unreal (listening/thinking/idle) and the page (also 'speaking')."""
        if state in ("listening", "thinking", "idle"):
            await self.hub.to_unreal({"type": "state", "state": state})
        await self.send_page({"type": "state", "state": state})

    async def interrupt(self) -> None:
        if self.reply_task and not self.reply_task.done():
            self.cancelled.set()
            self.reply_task.cancel()
            await self.hub.to_unreal({"type": "interrupt"})
            await self.send_page({"type": "interrupted"})

    async def utterance(self, pcm_b64: str, sample_rate: int) -> None:
        await self.interrupt()
        self.reply_task = asyncio.create_task(self._turn(base64.b64decode(pcm_b64), sample_rate))

    async def _turn(self, pcm: bytes, sample_rate: int) -> None:
        self.cancelled = threading.Event()
        cancelled = self.cancelled
        await self.state("thinking")
        t0 = time.perf_counter()
        config: PatientConfig | None = self.session.config
        language = language_code(config.language) if config else None
        try:
            text = await self.voice.transcribe(wav_bytes(pcm, sample_rate), language or None)
        except Exception as exc:  # network, quota, bad audio
            log.error("speech-to-text failed: %s", exc)
            await self.send_page({"type": "error", "message": f"Speech-to-text failed: {exc}"})
            await self.state("listening")
            return
        t_stt = time.perf_counter()
        if not text:
            await self.state("listening")
            return
        await self.send_page({"type": "student", "text": text})
        self.history.append({"role": "user", "content": text})

        sentences: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        client = self.session.client
        history = list(self.history)

        def produce() -> None:
            buffer = ""
            try:
                for piece in client.stream_reply(history):
                    if cancelled.is_set():
                        return
                    buffer += piece
                    ready, buffer = split_sentences(buffer)
                    for sentence in ready:
                        loop.call_soon_threadsafe(sentences.put_nowait, sentence)
                ready, _ = split_sentences(buffer, final=True)
                for sentence in ready:
                    loop.call_soon_threadsafe(sentences.put_nowait, sentence)
            except Exception as exc:
                log.error("LLM error: %s", exc)
                loop.call_soon_threadsafe(sentences.put_nowait, "Sorry... could you say that again?")
            finally:
                loop.call_soon_threadsafe(sentences.put_nowait, None)

        threading.Thread(target=produce, daemon=True).start()

        voice = choose_voice(config)
        instructions = voice_instructions(config, getattr(self.session, "mood", "neutral"))
        to_unreal = bool(self.hub.unreal)
        spoken: list[str] = []
        audio_seconds = 0.0
        speech_start: float | None = None
        first_audio: float | None = None
        try:
            while (sentence := await sentences.get()) is not None:
                spoken.append(sentence)
                await self.send_page({"type": "patient", "text": " ".join(spoken)})
                carry = b""
                async for chunk in self.voice.speak(sentence, voice, instructions):
                    data = carry + chunk
                    cut = len(data) - len(data) % CHUNK_BYTES if len(data) >= CHUNK_BYTES else 0
                    carry = data[cut:]
                    for i in range(0, cut, CHUNK_BYTES):
                        if speech_start is None:
                            speech_start = time.perf_counter()
                            first_audio = speech_start
                            await self.state("speaking")
                        await self._audio(data[i:i + CHUNK_BYTES], to_unreal)
                        audio_seconds += CHUNK_BYTES / 2 / TTS_SAMPLE_RATE
                if len(carry) >= 2:
                    carry = carry[: len(carry) - len(carry) % 2]
                    await self._audio(carry, to_unreal)
                    audio_seconds += len(carry) / 2 / TTS_SAMPLE_RATE
            if spoken:
                self.history.append({"role": "assistant", "content": " ".join(spoken)})
            log.info(
                "openai turn: stt=%.0fms first audio=%s | student: %.60s | patient: %.80s",
                (t_stt - t0) * 1000,
                f"{(first_audio - t0) * 1000:.0f}ms" if first_audio else "-",
                text, " ".join(spoken),
            )
            # Wait until the patient has finished speaking, then listen again.
            if speech_start is not None:
                remaining = speech_start + audio_seconds + 0.3 - time.perf_counter()
                if remaining > 0:
                    await asyncio.sleep(remaining)
            if to_unreal:
                await self.hub.to_unreal({"type": "state", "state": "idle"})
            await self.send_page({"type": "state", "state": "listening"})
        except asyncio.CancelledError:
            cancelled.set()
            if spoken:  # keep what the student heard
                self.history.append({"role": "assistant", "content": " ".join(spoken) + " —"})
            raise
        except Exception as exc:
            log.error("text-to-speech failed: %s", exc)
            await self.send_page({"type": "error", "message": f"Text-to-speech failed: {exc}"})
            await self.state("listening")

    async def _audio(self, pcm: bytes, to_unreal: bool) -> None:
        message = {"type": "audio", "sample_rate": TTS_SAMPLE_RATE, "pcm_b64": base64.b64encode(pcm).decode()}
        if to_unreal:
            await self.hub.to_unreal(message)
        else:
            await self.send_page(message)

    async def close(self) -> None:
        if self.reply_task and not self.reply_task.done():
            self.cancelled.set()
            self.reply_task.cancel()
