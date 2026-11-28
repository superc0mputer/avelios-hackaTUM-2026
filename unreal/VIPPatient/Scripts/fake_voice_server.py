"""Stand-in for engine/voice_server.py's /ws/unreal, to test the patient without the real backend.

Sends what the voice server sends (and the optional messages proposed in VIPBackendLink.h):
a case, an emotion, a reply as 16-bit PCM in small chunks like a live stream, the thinking state
before the reply, and an interrupt in the middle of the second reply.

    python3 unreal/VIPPatient/Scripts/fake_voice_server.py --wav reply.wav [--case cases/case-002.json]
    # then start the game with -VIPServer=ws://localhost:8787/ws/unreal

Make a test reply on macOS:  say -o reply.wav --data-format=LEI16@16000 "It started on Tuesday."
Needs the Python package "websockets".
"""

import argparse
import asyncio
import base64
import json
import wave

import websockets

CHUNK_SECONDS = 0.1  # ElevenLabs streams small chunks


def read_wav(path):
    with wave.open(path, "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise SystemExit("need a mono 16-bit WAV")
        return wav.getframerate(), wav.readframes(wav.getnframes())


async def stream(ws, rate, pcm, stop_after=None):
    step = int(rate * CHUNK_SECONDS) * 2
    sent = 0
    for start in range(0, len(pcm), step):
        chunk = pcm[start:start + step]
        await ws.send(json.dumps({"type": "audio", "sample_rate": rate, "pcm_b64": base64.b64encode(chunk).decode()}))
        sent += len(chunk)
        if stop_after and sent / 2 / rate >= stop_after:
            return
        await asyncio.sleep(CHUNK_SECONDS)


async def session(ws, args):
    rate, pcm = read_wav(args.wav)
    print("Unreal connected")
    if args.case:
        with open(args.case, encoding="utf-8") as f:
            case = json.load(f)
        if args.pain is not None or args.breathing or args.personality:
            case.setdefault("presentation", {})
            if args.pain is not None:
                case["presentation"]["pain"] = args.pain
            if args.breathing:
                case["presentation"]["breathing"] = args.breathing
            if args.personality:
                case.setdefault("personality", {})["type"] = args.personality
        await ws.send(json.dumps({"type": "case", "case": case}))
        print("sent case", case.get("case_id"))
    await asyncio.sleep(4)
    for turn in range(args.turns):
        await ws.send(json.dumps({"type": "state", "state": "thinking"}))
        print("turn", turn + 1, ": thinking")
        await asyncio.sleep(1.5)
        emotion = ["sad", "fear", "neutral"][turn % 3]
        await ws.send(json.dumps({"type": "emotion", "emotion": emotion, "intensity": 0.7}))
        interrupt = turn == 1
        print("turn", turn + 1, ": speaking", emotion, "(interrupted)" if interrupt else "")
        await stream(ws, rate, pcm, stop_after=1.5 if interrupt else None)
        if interrupt:
            await ws.send(json.dumps({"type": "interrupt"}))
        await ws.send(json.dumps({"type": "state", "state": "listening"}))
        await asyncio.sleep(4)
    print("done")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True)
    parser.add_argument("--case")
    parser.add_argument("--pain", type=float)
    parser.add_argument("--breathing")
    parser.add_argument("--personality")
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    done = asyncio.get_running_loop().create_future()

    async def handler(ws):
        try:
            await session(ws, args)
        finally:
            if not done.done():
                done.set_result(True)

    async with websockets.serve(handler, "127.0.0.1", args.port):
        print("waiting for Unreal on ws://localhost:%d/ws/unreal" % args.port)
        await done


if __name__ == "__main__":
    asyncio.run(main())
