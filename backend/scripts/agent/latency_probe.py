"""Measure how fast the agent answers, on a deployed environment, before and after a change.

Usage (from backend/):
    DEEPLINGO_PROBE_TOKEN=<access token> python scripts/agent/latency_probe.py \
        --base-url https://<api host> --wav speech_16k_mono.wav [--runs 3] [--channel voice|text|both]

The token is read from the environment and never printed. The WAV is a short learner utterance (16 kHz, 16-bit,
mono). Only timings are recorded: no audio, transcript or payload is written.

Voice (the Live WebSocket), per run:
- utterance_end_to_speech_ms: last audio frame of the utterance sent -> first agent audio frame received.
- interrupt_to_stop_ms: the learner starts speaking over the agent -> the server's "interrupted" event.
Text (`/companion/turns` with the same WAV), per run:
- turn_round_trip_ms: request sent -> the whole turn (reply, audio) received.

Every run costs real model and speech calls; the owner approves the environment and the budget first.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

PREFIX = "/api/v1/v3"
FRAME_MS = 20
SAMPLE_RATE = 16_000
# Targets taken from Companion Space's classroom probe (evals/latency_probe.py), adapted to this agent.
TARGETS_MS = {
    "utterance_end_to_speech_ms": 1800,
    "interrupt_to_stop_ms": 300,
    "turn_round_trip_ms": 3000,
}


@dataclass
class Samples:
    values: dict[str, list[float]] = field(default_factory=dict)

    def add(self, metric: str, value: float | None) -> None:
        if value is not None and math.isfinite(value) and value >= 0:
            self.values.setdefault(metric, []).append(value)


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def summarize(samples: Samples) -> list[dict]:
    """One row per metric: count, p50, p90, max and whether p50 meets the target."""
    rows = []
    for metric, values in sorted(samples.values.items()):
        p50 = statistics.median(values)
        target = TARGETS_MS.get(metric)
        rows.append({"metric": metric, "n": len(values), "p50": round(p50), "p90": round(percentile(values, 0.9)),
                     "max": round(max(values)), "target": target,
                     "meets": None if target is None else p50 <= target})
    return rows


def pcm_frames(pcm: bytes, frame_ms: int = FRAME_MS, rate: int = SAMPLE_RATE) -> list[bytes]:
    """16-bit mono PCM cut into frames of `frame_ms` (the last one padded with silence)."""
    size = rate * 2 * frame_ms // 1000
    frames = [pcm[i:i + size] for i in range(0, len(pcm), size)]
    if frames and len(frames[-1]) < size:
        frames[-1] = frames[-1] + b"\0" * (size - len(frames[-1]))
    return frames


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2 or handle.getframerate() != SAMPLE_RATE:
            raise SystemExit("The WAV must be 16 kHz, 16-bit, mono.")
        return handle.readframes(handle.getnframes())


async def _send_realtime(ws, frames: list[bytes]) -> float:
    """Send frames at real-time pace; returns the clock when the last one went out."""
    for frame in frames:
        await ws.send(frame)
        await asyncio.sleep(FRAME_MS / 1000)
    return time.perf_counter()


async def probe_voice(base_url: str, token: str, pcm: bytes, samples: Samples, timeout_s: float = 30) -> None:
    from websockets.asyncio.client import connect

    url = base_url.replace("https://", "wss://").replace("http://", "ws://") + PREFIX + "/learner/me/companion/realtime"
    frames = pcm_frames(pcm)
    silence = [b"\0" * len(frames[0])] * 50  # one second, so the provider's end-of-turn detection fires
    async with connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        await ws.send(json.dumps({"type": "start", "entry": "home"}))
        await _until(ws, lambda kind, data: kind == "json" and data.get("type") == "ready", timeout_s)
        # The agent greets first: wait for its turn to finish before the learner speaks.
        await _until(ws, lambda kind, data: kind == "json" and data.get("type") == "turn_complete", timeout_s)
        sent_at = await _send_realtime(ws, frames + silence) - len(silence) * FRAME_MS / 1000
        first_audio = await _until(ws, lambda kind, _: kind == "bytes", timeout_s)
        samples.add("utterance_end_to_speech_ms", (first_audio - sent_at) * 1000 if first_audio else None)
        # Barge in while the agent speaks.
        barge_at = time.perf_counter()
        speaker = asyncio.create_task(_send_realtime(ws, frames))
        stopped = await _until(ws, lambda kind, data: kind == "json" and data.get("type") == "interrupted", timeout_s)
        samples.add("interrupt_to_stop_ms", (stopped - barge_at) * 1000 if stopped else None)
        await speaker
        await ws.send(json.dumps({"type": "end"}))


async def _until(ws, predicate, timeout_s: float) -> float | None:
    """Read messages until one matches; returns the clock at that message, None on timeout or close."""
    deadline = time.perf_counter() + timeout_s
    while (left := deadline - time.perf_counter()) > 0:
        try:
            raw = await asyncio.wait_for(ws.recv(), left)
        except (asyncio.TimeoutError, Exception):
            return None
        at = time.perf_counter()
        kind, data = ("bytes", None) if isinstance(raw, bytes) else ("json", _json(raw))
        if predicate(kind, data or {}):
            return at
    return None


def _json(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def probe_text(base_url: str, token: str, wav_bytes: bytes, samples: Samples) -> None:
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=base_url + PREFIX, headers=headers, timeout=60) as client:
        started = client.post("/learner/me/companion/sessions", json={"entry": "home"})
        started.raise_for_status()
        ticket = started.json()["session_ticket"]
        sent = time.perf_counter()
        turn = client.post("/learner/me/companion/turns", data={"session_ticket": ticket},
                           files={"audio": ("turn.wav", wav_bytes, "audio/wav")})
        samples.add("turn_round_trip_ms", (time.perf_counter() - sent) * 1000 if turn.status_code == 200 else None)
        if turn.status_code == 200 and turn.json().get("session_ticket"):
            client.post("/learner/me/companion/finish", json={"session_ticket": turn.json()["session_ticket"]})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--wav", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--channel", choices=("voice", "text", "both"), default="both")
    args = parser.parse_args()
    token = os.environ.get("DEEPLINGO_PROBE_TOKEN", "").strip()
    if not token:
        print("Set DEEPLINGO_PROBE_TOKEN.", file=sys.stderr)
        return 2
    pcm = read_wav(args.wav)
    wav_bytes = args.wav.read_bytes()
    base = args.base_url.rstrip("/")
    samples = Samples()
    for run in range(args.runs):
        if args.channel in ("voice", "both"):
            try:
                asyncio.run(probe_voice(base, token, pcm, samples))
            except Exception as exc:
                print(f"voice run {run + 1} failed: {type(exc).__name__}", file=sys.stderr)
        if args.channel in ("text", "both"):
            try:
                probe_text(base, token, wav_bytes, samples)
            except Exception as exc:
                print(f"text run {run + 1} failed: {type(exc).__name__}", file=sys.stderr)
    for row in summarize(samples):
        verdict = "" if row["meets"] is None else ("OK" if row["meets"] else "OVER")
        print(f"{row['metric']:<30} n={row['n']} p50={row['p50']}ms p90={row['p90']}ms max={row['max']}ms "
              f"target={row['target']}ms {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
