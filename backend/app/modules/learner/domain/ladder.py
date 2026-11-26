"""The usage ladder for one target: R0 seen .. R5 durable use, computed from its events.

The ladder answers "have I used this word yet?". Every rung change is explained by events, so the
stored rung is only a projection: `rung_from_events` recomputes it and must always agree with it.

    R0 seen          the word was met (no event needed)
    R1 recognised    a correct recognition event (choose the meaning)
    R2 recalled      a correct recall event (say or type it from a cue)
    R3 framed use    a correct framed_use event (a sentence with a frame or a hint on screen)
    R4 spontaneous   a correct spontaneous_use event (the learner said it, unprompted, correctly)
    R5 durable       correct spontaneous uses on two days at least three days apart, in two
                     different contexts when both contexts are known

Two consecutive misses at or below the current rung step the learner down one rung; one miss at the
spontaneous level ends R5. A correct event resets the miss count. All thresholds are proposals that
the first real data should confirm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from zoneinfo import ZoneInfo


class EventKind(str, Enum):
    SEEN = "seen"
    RECOGNITION = "recognition"
    RECALL = "recall"
    FRAMED_USE = "framed_use"
    SPONTANEOUS_USE = "spontaneous_use"


class Outcome(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"


LEVEL_OF_KIND = {
    EventKind.SEEN: 0,
    EventKind.RECOGNITION: 1,
    EventKind.RECALL: 2,
    EventKind.FRAMED_USE: 3,
    EventKind.SPONTANEOUS_USE: 4,
}
MAX_RUNG = 5
MISSES_TO_STEP_DOWN = 2
DURABLE_MIN_DAYS_APART = 3


@dataclass(frozen=True)
class TargetEvent:
    kind: EventKind
    outcome: Outcome
    occurred_at: datetime
    context_key: str | None = None


@dataclass(frozen=True)
class LadderState:
    rung: int = 0
    misses: int = 0
    # Correct spontaneous uses since the last step down: (local date, context key).
    hits: tuple[tuple[date, str | None], ...] = field(default_factory=tuple)


def _is_durable(hits: tuple[tuple[date, str | None], ...]) -> bool:
    ordered = sorted(hits, key=lambda item: item[0])
    for index, (first_day, first_context) in enumerate(ordered):
        for second_day, second_context in ordered[index + 1:]:
            if (second_day - first_day).days < DURABLE_MIN_DAYS_APART:
                continue
            if first_context is None or second_context is None or first_context != second_context:
                return True
    return False


def apply_event(state: LadderState, event: TargetEvent, tz: ZoneInfo) -> LadderState:
    level = LEVEL_OF_KIND[event.kind]
    if level == 0:
        return state
    if event.outcome == Outcome.CORRECT:
        rung = max(state.rung, level)
        hits = state.hits
        if event.kind == EventKind.SPONTANEOUS_USE:
            local_day = event.occurred_at.astimezone(tz).date()
            hits = (*hits, (local_day, event.context_key))
            if _is_durable(hits):
                rung = MAX_RUNG
        return LadderState(rung=rung, misses=0, hits=hits)
    # Incorrect
    if state.rung == MAX_RUNG and event.kind == EventKind.SPONTANEOUS_USE:
        return LadderState(rung=MAX_RUNG - 1, misses=0, hits=())
    if level > state.rung:
        return state  # a failed attempt to climb changes nothing
    misses = state.misses + 1
    if misses >= MISSES_TO_STEP_DOWN:
        return LadderState(rung=max(state.rung - 1, 0), misses=0, hits=())
    return LadderState(rung=state.rung, misses=misses, hits=state.hits)


def replay(events: list[TargetEvent], tz: ZoneInfo) -> LadderState:
    state = LadderState()
    for event in sorted(events, key=lambda item: item.occurred_at):
        state = apply_event(state, event, tz)
    return state


def rung_from_events(events: list[TargetEvent], tz: ZoneInfo) -> int:
    return replay(events, tz).rung
