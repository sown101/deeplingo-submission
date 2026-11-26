"""A text conversation kept on the server between turns (PRD 8.12, TARGET_DESIGN §7).

The text channel answers one request per turn. What must last from one turn to the next is a `TextSession` (the
core's `AgentSession` plus the text channel's own counters), stored as a JSON-ready dict in a `SessionStore` under
the conversation id and the learner id; the client holds only a short signed reference to it. The state holds the
conversation's server-built context, the agent loop's messages (with earlier tool calls and their results, within
`MAX_STATE_MESSAGE_CHARS`), what help was shown and the per-conversation counters, and the support delivered (FR-3.5
evidence). Never audio. It expires with the conversation and is deleted when the conversation finishes.

`MemorySessionStore` is the store of one API process (bounded, with expiry), used in tests and when no Redis is
configured; the Redis store is in the learning module's infrastructure.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import get_args
from uuid import UUID

from app.modules.learning.application.agent.ports import CompanionTicket
from app.modules.learning.application.agent.session import AgentSession, Mode
from app.modules.learning.application.agent.setup import PreparedConversation
from app.modules.learning.application.session_events import LearnerTurn
from app.modules.learning.domain.companion import (
    MAX_HISTORY_MESSAGES,
    CompanionEntry,
    CompanionItem,
    CompanionMessage,
    RegionLine,
)

STATE_VERSION = 1
# What earlier turns may add to the model's input: about 12k tokens. Tool exchanges of the oldest turns go first
# (their answers stay), then the oldest whole turns; the opening turn and the latest turn are always kept.
MAX_STATE_MESSAGE_CHARS = 48_000
MAX_KEPT_LEARNER_TURNS = 40  # FR-3.5 evidence: learner turns kept for the end-of-session analysis
MAX_WEAK_WORDS = 6


@dataclass
class TextSession(AgentSession):
    """The core session plus what only the text channel keeps between its requests."""

    turn: int = 0  # learner turns taken (a help button without words is a turn too)
    messages: list[dict] = field(default_factory=list)  # the agent loop's conversation so far, as the model saw it
    used_item_ids: list[str] = field(default_factory=list)
    weak_words: list[str] = field(default_factory=list)
    speech_ms: int = 0
    text_only: bool = False
    token_id: str = ""  # the one token that may continue this conversation
    defer_memory: bool = True  # a turn that fails is retried with the same ticket: memory is written once it is spent


def bounded(messages: list[dict], limit: int = MAX_STATE_MESSAGE_CHARS) -> list[dict]:
    """The conversation within `limit` characters, cut only between turns so every tool call keeps its result."""
    turns: list[list[dict]] = []
    for message in messages:
        if message.get("role") == "user" or not turns:
            turns.append([])
        turns[-1].append(message)

    def size() -> int:
        return sum(len(json.dumps(message, ensure_ascii=False)) for turn in turns for message in turn)

    for turn in turns[1:-1]:  # first: drop the tool exchanges of the oldest turns, keeping what was said
        if size() <= limit:
            break
        turn[:] = [message for message in turn if message.get("role") != "tool" and not message.get("tool_calls")]
    while size() > limit and len(turns) > 2:
        del turns[1]  # then the oldest whole turns; the opening and the latest stay
    return [message for turn in turns for message in turn]


def dump_state(session: TextSession) -> dict:
    """The conversation as a JSON-ready dict (no audio, no learner id: the store's key holds it)."""
    ticket = session.ticket
    return {
        "v": STATE_VERSION,
        "context": {
            "lang": ticket.language_code, "sup": ticket.support_language_code, "entry": ticket.entry.value,
            "lib": str(ticket.library_item_id) if ticket.library_item_id else None, "topic": ticket.topic,
            "items": [{"id": item.item_id, "t": item.text, "m": item.meaning, "f": list(item.forms),
                       "p": item.practiced} for item in ticket.items],
            "ex": ticket.excerpt,
            # Region lines without their text: the excerpt already holds it.
            "reg": [{"r": line.ref, "id": line.segment_id, "a": line.start_ms, "b": line.end_ms}
                    for line in ticket.region_lines],
            "began": ticket.started_at.isoformat(), "scenario": ticket.scenario_id, "swapped": ticket.swap_roles,
            "rid": ticket.region_id,
        },
        "token": session.token_id,
        "mode": session.mode,
        "text_only": session.text_only,
        "turn": session.turn,
        "messages": bounded(session.messages),
        "history": [{"r": message.role, "x": message.text} for message in session.history[-MAX_HISTORY_MESSAGES:]],
        "help": {"requests": session.help_requests, "stalls": session.scaffolding.level,
                 "hint_step": session.scaffolding.hint_step, "taps": session.scaffolding.taps},
        "counts": {"memories": session.memories, "today_edits": session.today_edits,
                   "study_requests": session.study_requests, "redo": sorted(session.redo_points),
                   "tools": session.tool_calls,
                   "pace": [session.pace, session.pace_successes, session.pace_long]},
        "evidence": {"turns": [turn.model_dump(mode="json") for turn in session.analysis_turns],
                     "examples": list(session.examples), "truncated": session.support_truncated,
                     "used": list(session.used_item_ids), "weak": list(session.weak_words),
                     "speech_ms": session.speech_ms},
    }


def load_state(data: dict, user, conversation_id: UUID) -> TextSession:
    """The session back from its stored dict. Raises ValueError (or KeyError/TypeError) on a value it cannot use."""
    if data.get("v") != STATE_VERSION:
        raise ValueError("unsupported conversation state")
    context = data["context"]
    ticket = CompanionTicket(
        user_id=user.id, language_code=context["lang"], support_language_code=context["sup"],
        entry=CompanionEntry(context["entry"]), library_item_id=UUID(context["lib"]) if context["lib"] else None,
        topic=context["topic"],
        items=tuple(CompanionItem(item_id=item["id"], text=item["t"], meaning=item["m"], forms=tuple(item["f"]),
                                  practiced=item["p"]) for item in context["items"]),
        excerpt=context["ex"],
        region_lines=tuple(RegionLine(ref=line["r"], segment_id=line["id"], start_ms=line["a"], end_ms=line["b"])
                           for line in context["reg"]),
        session_id=conversation_id, started_at=datetime.fromisoformat(context["began"]),
        scenario_id=context["scenario"], swap_roles=context["swapped"], region_id=context["rid"])
    session = TextSession(user=user, prepared=PreparedConversation(ticket=ticket), id=conversation_id,
                          text_only=data.get("text_only") is True,
                          token_id=data["token"], turn=data["turn"], messages=list(data["messages"]),
                          history=[CompanionMessage(role=message["r"], text=message["x"])
                                   for message in data["history"]])
    if data.get("mode") is not None:  # a state saved before the mode was kept falls back to the ticket's mode
        if data["mode"] not in get_args(Mode):
            raise ValueError("unsupported conversation mode")
        session.mode = data["mode"]
    help_, counts, evidence = data["help"], data["counts"], data["evidence"]
    session.help_requests = help_["requests"]
    session.scaffolding.level, session.scaffolding.hint_step = help_["stalls"], help_["hint_step"]
    session.scaffolding.taps = help_["taps"]
    session.memories, session.today_edits = counts["memories"], counts["today_edits"]
    session.study_requests, session.redo_points = counts["study_requests"], set(counts["redo"])
    session.tool_calls = int(counts.get("tools", 0))  # absent in a state saved before the limit existed
    pace = counts.get("pace") or [None, 0, 0]
    session.pace, session.pace_successes, session.pace_long = pace[0], int(pace[1]), int(pace[2])
    session.analysis_turns = [LearnerTurn.model_validate(turn) for turn in evidence["turns"]]
    session.examples, session.support_truncated = list(evidence["examples"]), evidence["truncated"]
    session.used_item_ids, session.weak_words = list(evidence["used"]), list(evidence["weak"])
    session.speech_ms = evidence["speech_ms"]
    return session


class MemorySessionStore:
    """The `SessionStore` of one API process: bounded, with expiry. A restart or a second process does not see it."""

    def __init__(self, *, max_entries: int = 5000, clock: Callable[[], float] = time.monotonic):
        self.max_entries = max_entries
        self.clock = clock
        self._values: dict[tuple, tuple[float, str]] = {}  # key -> (expiry, JSON): a copy, never the live object
        self._lock = threading.Lock()

    def get(self, conversation_id: UUID, user_id: UUID) -> dict | None:
        with self._lock:
            found = self._values.get(("state", conversation_id, user_id))
            if found is None or found[0] <= self.clock():
                return None
            return json.loads(found[1])

    def put(self, conversation_id: UUID, user_id: UUID, state: dict, *, ttl_seconds: int) -> None:
        value = json.dumps(state, ensure_ascii=False)
        with self._lock:
            self._set(("state", conversation_id, user_id), value, ttl_seconds)

    def delete(self, conversation_id: UUID, user_id: UUID) -> None:
        with self._lock:
            self._values.pop(("state", conversation_id, user_id), None)

    def claim(self, conversation_id: UUID, user_id: UUID, token_id: str, *, ttl_seconds: int) -> bool:
        key = ("used", conversation_id, user_id, token_id)
        with self._lock:
            found = self._values.get(key)
            if found is not None and found[0] > self.clock():
                return False
            self._set(key, "1", ttl_seconds)
            return True

    def release(self, conversation_id: UUID, user_id: UUID, token_id: str) -> None:
        with self._lock:
            self._values.pop(("used", conversation_id, user_id, token_id), None)

    def _set(self, key: tuple, value: str, ttl_seconds: int) -> None:
        now = self.clock()
        if len(self._values) >= self.max_entries:
            self._values = {name: entry for name, entry in self._values.items() if entry[0] > now}
            while len(self._values) >= self.max_entries:  # still full: the entry that expires first goes
                del self._values[min(self._values, key=lambda name: self._values[name][0])]
        self._values[key] = (now + max(1, ttl_seconds), value)


def seconds_until(moment: datetime) -> int:
    """A store lifetime that ends with the conversation (at least one second)."""
    return max(1, int((moment - datetime.now(UTC)).total_seconds()) + 1)
