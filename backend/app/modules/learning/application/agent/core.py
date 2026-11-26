"""AgentCore: one agent behind both channels (TARGET_DESIGN §7, agent harness plan phase 1).

The text channel (the agent loop, loop.py) and the voice channel (Gemini Live calling functions itself) reach the
tools and the reply rules through this one object, so the agent obeys the same limits and checks wherever the
learner talks to it. The agent still decides what to do; the core only owns what the server must decide alone:
- which tools this conversation offers, and how many calls a turn and a session may make;
- what a reply may say: a grading claim or a reply outside the level's language policy is sent back to the agent
  to say again; on voice, where the turn has already been heard, a grading claim ends the session and a third
  slip in a row ends it ("policy").
Every call gets a response; a refused call is an error the model can read, never an exception.

How calls run (phase 2, after DeepTutor's tool_dispatch and tool_arg_guard):
- a call the tool refused while a required argument was missing or blank comes back naming those arguments and
  their expected shape, so the model fills them in instead of repeating the call (the tool's own answer is kept);
- the same call (name and arguments) twice in one batch runs once: the repeat gets the first result, without
  showing anything again; it still counts against the limits;
- reads of one batch run concurrently; display and action tools run one at a time, in the model's order;
- every call has a deadline; a read that misses it is tried once more.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.learning.application.agent.prompts import REPLY_END, REPLY_SEPARATOR, language_slip_note
from app.modules.learning.application.agent.session import AgentSession
from app.modules.learning.application.agent.tools import ToolRegistry, ToolResult, ToolSpec
from app.modules.learning.application.speaking_prompts import language_name
from app.modules.learning.domain.companion import level_policy, reply_in_learning_script, reply_within_policy
from app.modules.learning.domain.realtime import language_slip, makes_grading_claim, transcript_breach
from app.modules.learning.domain.speaking import spoken_unit_count
from app.platform.observability.port import current_turn

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8  # calls one agent turn may make; further ones are refused
MAX_SESSION_TOOL_CALLS = 80  # calls a whole conversation may make (a model calling in a loop must stop)
# Agent turns in a row outside the language policy before a voice session ends: the agent is asked to say it again
# twice; a third slip in a row means the model is not following its rules, so the session must not loop.
MAX_LANGUAGE_SLIPS = 3
TOOL_TIMEOUT_S = 8.0  # one call, end to end; a read's own data source is bounded tighter (tools.LOOKUP_TIMEOUT_S)
EXPLANATION_UNITS_MAX = 60  # a text reply in the support language (A1-A2 explanations) is longer than a spoken one


@dataclass(frozen=True)
class VoiceVerdict:
    """What the voice channel does with an agent turn it has already relayed."""
    end: bool = False  # the session ends ("policy"); `breach` says why
    breach: str | None = None
    note: str | None = None  # a message for the agent: say it again


def split_reply(text: str) -> tuple[str, str, bool]:
    """The spoken reply, its support-language version (the same text when the agent gave only one) and whether the
    agent ended the conversation (a last line with only `[end]`)."""
    lines = text.strip().splitlines()
    ended = bool(lines) and lines[-1].strip() == REPLY_END
    lines = lines[:-1] if ended else lines
    cut = next((index for index, line in enumerate(lines) if line.strip() == REPLY_SEPARATOR), None)
    reply = " ".join(" ".join(lines[:cut]).split())
    support = " ".join(" ".join(lines[cut + 1:]).split()) if cut is not None else ""
    return reply, support or reply, ended


def _call_key(name: str, args) -> str:
    try:
        return name + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return name + repr(args)


_DECLINED = ("shown", "found", "created", "opened", "edited", "started", "offered", "remembered", "forgotten",
             "noted")


def _declined(response: dict) -> bool:
    """The tool did nothing and said no more than that (no reason of its own)."""
    if response.get("error") == "invalid arguments":
        return True
    return "reason" not in response and any(response.get(key) is False for key in _DECLINED)


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or (
        isinstance(value, (list, dict)) and not value)


def missing_arguments(spec: ToolSpec, args) -> dict | None:
    """Guidance for a call without one of its required arguments (absent or blank), naming each with its expected
    shape, so the model fills them in instead of repeating the call; None when nothing required is missing."""
    values = args if isinstance(args, dict) else {}
    properties = spec.parameters.get("properties", {})
    missing = [name for name in spec.parameters.get("required", []) if _blank(values.get(name))]
    if not missing:
        return None
    expected = {}
    for name in missing:
        schema = properties.get(name, {})
        shape = schema.get("type", "value")
        if "enum" in schema:
            shape += " (one of: " + ", ".join(map(str, schema["enum"])) + ")"
        expected[name] = shape + (": " + schema["description"] if schema.get("description") else "")
    return {"missing": missing, "expected": expected,
            "note": f"Nothing was done. Call {spec.name} again with {', '.join(missing)} filled in; the same call "
                    "without them does nothing again."}


def declared_level(session: AgentSession) -> str | None:
    return session.context.declared_level if session.context else None


class AgentCore:
    def __init__(self, registry: ToolRegistry, specs: Sequence[ToolSpec], *, max_turn_calls: int = MAX_TOOL_CALLS,
                 max_session_calls: int = MAX_SESSION_TOOL_CALLS):
        self.registry = registry
        self.specs = tuple(specs)
        self.allowed = frozenset(spec.name for spec in self.specs)
        self.max_turn_calls, self.max_session_calls = max_turn_calls, max_session_calls
        self.by_name = {spec.name: spec for spec in self.specs}
        self.timeout_s = TOOL_TIMEOUT_S

    # --- Tools -------------------------------------------------------------------------------

    @staticmethod
    def begin_turn(session: AgentSession) -> None:
        """A new agent turn: its call count starts again (the session's does not)."""
        session.turn_tool_calls = 0

    def refusal(self, session: AgentSession, name: str) -> dict | None:
        """The error a call gets without running, or None when it may run; a counted call is charged here."""
        if name not in self.allowed:
            return {"error": "unknown function"}
        session.turn_tool_calls += 1
        session.tool_calls += 1
        if session.turn_tool_calls > self.max_turn_calls or session.tool_calls > self.max_session_calls:
            return {"error": "too many calls"}
        return None

    async def call(self, session: AgentSession, name: str, args) -> ToolResult:
        refused = self.refusal(session, name)
        if refused is not None:
            return ToolResult(refused, refused=True)
        result = await self._dispatch(session, name, args)
        guidance = missing_arguments(self.by_name[name], args) if _declined(result.response) else None
        if guidance is not None:
            result.response = {**result.response, **guidance}
        return result

    async def run_calls(self, session: AgentSession, calls: Sequence[tuple[str, object]]) -> list[ToolResult]:
        """One batch of calls (name, arguments), results in the batch's order: reads at once, the rest in order, and a
        repeat of a call in the batch answered with the first one's result."""
        turn_trace = current_turn()

        async def call(index: int) -> ToolResult:
            name, args = calls[index]
            if turn_trace is None:
                return await self.call(session, name, args)
            # An unrecognized name is model output and may contain learner data.
            with turn_trace.span("tool", name if name in self.allowed else "unknown") as span:
                result = await self.call(session, name, args)
                if span is not None:
                    if result.refused:
                        span.status = "refused"
                    elif "error" in result.response:
                        span.status = "error"
                    elif _declined(result.response):
                        span.status = "declined"
                return result

        results: list[ToolResult | None] = [None] * len(calls)
        first: dict[str, int] = {}
        repeats: dict[int, int] = {}
        for index, (name, args) in enumerate(calls):
            key = _call_key(name, args)
            if key in first:
                repeats[index] = first[key]
            else:
                first[key] = index
        reads = [index for index, (name, _) in enumerate(calls)
                 if index not in repeats and self.kind(name) == "read"]
        if reads:
            done = await asyncio.gather(*(call(index) for index in reads))
            for index, result in zip(reads, done):
                results[index] = result
        for index, (name, args) in enumerate(calls):
            if index in repeats:
                refused = self.refusal(session, name)  # a repeat still counts
                original = results[repeats[index]]
                results[index] = (ToolResult(refused, refused=True) if refused is not None
                                  else ToolResult(dict(original.response), refused=original.refused))
            elif results[index] is None:
                results[index] = await call(index)
        return results

    def kind(self, name: str) -> str | None:
        spec = self.by_name.get(name)
        return spec.kind if spec else None

    async def _dispatch(self, session: AgentSession, name: str, args) -> ToolResult:
        attempts = 2 if self.kind(name) == "read" else 1  # an action is never repeated: it may have happened
        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.wait_for(self.registry.call(session, name, args), self.timeout_s)
            except TimeoutError:
                logger.warning("agent tool timed out tool=%s attempt=%s", name, attempt)
        return ToolResult({"error": "timeout", "note": f"{name} did not answer in time. Do not call it again in this "
                                                       "turn; answer the learner without it."})

    # --- Replies -----------------------------------------------------------------------------

    @staticmethod
    def text_reply_note(session: AgentSession, text: str) -> str | None:
        """The text channel's language policy (PRD 8.12 point 2): a slip is sent back to the agent, never a reason to
        end the session. None when the reply may be sent."""
        ticket = session.ticket
        policy = level_policy(ticket.language_code, declared_level(session))
        reply, support, _ = split_reply(text)
        if not reply:
            return "(Your reply was empty. Answer the learner.)"
        if makes_grading_claim(reply) or makes_grading_claim(support):
            return "(Never give the learner a score, points, a grade or a level. Say it again without one.)"
        in_script = reply_in_learning_script(reply)
        if not in_script and not policy.explains_in_support:
            return language_slip_note(policy, learning=language_name(ticket.language_code),
                                      support=language_name(ticket.support_language_code))
        within = (reply_within_policy(reply, ticket.language_code, declared_level(session)) if in_script
                  else spoken_unit_count(reply, ticket.language_code) <= EXPLANATION_UNITS_MAX)
        if not within:
            return "(Your reply was too long. Say it again, shorter.)"
        return None

    @staticmethod
    def voice_reply(session: AgentSession, reply: str) -> VoiceVerdict:
        """The voice channel's check of a finished agent turn (the learner has heard it): a grading claim ends the
        session; a slip is sent back to the agent, and the session ends after MAX_LANGUAGE_SLIPS in a row."""
        ticket = session.ticket
        if transcript_breach(reply, ticket.language_code) == "grading_claim":
            return VoiceVerdict(end=True, breach="grading_claim")
        policy = level_policy(ticket.language_code, declared_level(session))
        slip = language_slip(reply, ticket.language_code, support_language_code=ticket.support_language_code,
                             explains_in_support=policy.explains_in_support)
        if slip is None:
            if reply.strip():
                session.language_slips = 0
            return VoiceVerdict()
        session.language_slips += 1
        if session.language_slips >= MAX_LANGUAGE_SLIPS:
            return VoiceVerdict(end=True, breach=slip)
        return VoiceVerdict(note=language_slip_note(policy, learning=language_name(ticket.language_code),
                                                    support=language_name(ticket.support_language_code)))
