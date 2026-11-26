"""Content-free trace of one companion call.

One log line per start, turn or finish: phase timings, outcome category and counts only. No
transcript, reply, hint, correction or topic text or identifier is recorded, so the
trace can stay on in every environment. Token counts are already logged by the provider
(`llm_usage`); this line gives the latency and outcome side of the same turn.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter

logger = logging.getLogger(__name__)

PHASES = ("context", "transcribe", "model", "tool", "synth")


@dataclass
class CompanionTrace:
    phase: str
    entry: str | None = None
    language: str | None = None
    outcome: str = "ok"
    turn: int | None = None
    model_attempts: int = 0
    last_rejection: str | None = None
    agent: str | None = None  # Respond, lookup or fallback; None when tools are off
    tool: str | None = None
    reply_units: int | None = None
    has_correction: bool | None = None
    next: str | None = None
    used_items: int | None = None
    audio: str | None = None
    # M1 S3: region context used, and the practice suggestion shown or dropped (no content).
    region: bool | None = None
    suggestion: str | None = None
    total_ms: int = 0
    phase_ms: dict[str, int] = field(default_factory=dict)

    @contextmanager
    def timed(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.phase_ms[name] = self.phase_ms.get(name, 0) + round((perf_counter() - started) * 1000)

    def emit(self) -> None:
        parts = [f"phase={self.phase}", f"entry={self.entry}", f"language={self.language}",
                 f"outcome={self.outcome}", f"turn={self.turn}", f"total_ms={self.total_ms}"]
        parts += [f"{name}_ms={self.phase_ms[name]}" for name in PHASES if name in self.phase_ms]
        parts += [f"model_attempts={self.model_attempts}", f"last_rejection={self.last_rejection}",
                  f"agent={self.agent}", f"tool={self.tool}",
                  f"reply_units={self.reply_units}", f"correction={self.has_correction}",
                  f"next={self.next}", f"used_items={self.used_items}", f"audio={self.audio}",
                  f"region={self.region}", f"suggestion={self.suggestion}"]
        logger.info("companion_trace " + " ".join(parts))


@contextmanager
def traced(phase: str, *, entry: str | None = None) -> Iterator[CompanionTrace]:
    """Time one call and emit its trace; a failure records its stable code, never its message."""
    trace = CompanionTrace(phase=phase, entry=entry)
    started = perf_counter()
    try:
        yield trace
    except Exception as exc:
        trace.outcome = str(getattr(exc, "code", None) or type(exc).__name__)
        raise
    finally:
        trace.total_ms = round((perf_counter() - started) * 1000)
        trace.emit()
