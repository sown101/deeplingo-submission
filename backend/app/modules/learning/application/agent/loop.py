"""The agent loop (TARGET_DESIGN §7): model -> tool calls -> results -> model, until the model answers.

One loop for the learner-facing agent: it takes the session, the system prompt, the conversation so far and the
tools to offer, and asks the model (native function calling) until it answers in text. Tools stay the only way the
agent reads or changes anything: every call goes through `ToolRegistry.call`, which keeps its argument checks,
own-data-only reads and confirmations. The loop is bounded by steps and wall-clock time; on the last step the
model gets no tools, so it must answer. The caller may reject an answer (`validate` returns a note for the model,
for example a language slip) and the loop asks again within the same budget instead of ending the session.
Anything the agent says counts as support for the words it contains (`AgentSession.note_support`, FR-3.5).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.modules.learning.application.agent.core import MAX_TOOL_CALLS, AgentCore  # noqa: F401 (re-exported)
from app.modules.learning.application.agent.session import AgentSession
from app.modules.learning.application.agent.tools import ToolRegistry, ToolSpec
from app.platform.llm.port import ToolCallingModel, ToolDefinition
from app.platform.observability.port import current_turn

logger = logging.getLogger(__name__)

MAX_STEPS = 6  # model calls per turn, the last one without tools
MAX_SECONDS = 12.0  # wall clock for the whole turn
MAX_RESULT_CHARS = 2500  # what a tool result may add to the conversation


class AgentLoopError(Exception):
    """The agent could not answer within its budget (`reason`: model, timeout, empty, rejected)."""

    def __init__(self, reason: str, steps: int = 0):
        super().__init__(reason)
        self.reason, self.steps = reason, steps  # how many model calls were made


@dataclass
class LoopResult:
    text: str
    events: list[dict] = field(default_factory=list)  # what the tools put on the learner's screen, in order
    tools: list[str] = field(default_factory=list)  # tool names the agent called, in order
    # The turn's tool calls and their results as conversation messages (rejected answers left out), so a channel
    # that keeps the conversation can give them to the model again in later turns.
    messages: list[dict] = field(default_factory=list)
    steps: int = 0
    rejections: int = 0


Validate = Callable[[str], "str | None"]


def tool_definitions(specs: Sequence[ToolSpec]) -> list[ToolDefinition]:
    return [ToolDefinition(spec.name, spec.description, spec.parameters) for spec in specs]


def _result_text(response: dict) -> str:
    # Tool text is data: angle brackets are removed so it cannot imitate the prompt's markers.
    body = json.dumps(response, ensure_ascii=False, default=str).replace("<", " ").replace(">", " ")
    return body[:MAX_RESULT_CHARS]


class AgentLoop:
    def __init__(self, model: ToolCallingModel, registry: ToolRegistry, *, max_steps: int = MAX_STEPS,
                 max_seconds: float = MAX_SECONDS, clock: Callable[[], float] = time.monotonic,
                 temperature: float = 0.5, max_tokens: int = 1500):
        self.model, self.registry = model, registry
        self.max_steps, self.max_seconds, self.clock = max_steps, max_seconds, clock
        self.temperature, self.max_tokens = temperature, max_tokens

    async def run(self, session: AgentSession, system_prompt: str, messages: Sequence[dict],
                  specs: Sequence[ToolSpec], *, validate: Validate | None = None,
                  deadline: float | None = None) -> LoopResult:
        conversation = [{"role": "system", "content": system_prompt}, *messages]
        definitions = tool_definitions(specs)
        core = AgentCore(self.registry, specs)  # the tools offered and their limits, as on the voice channel
        core.begin_turn(session)
        result = LoopResult(text="")
        turn_trace = current_turn()
        if deadline is None:
            deadline = self.clock() + self.max_seconds
        for step in range(1, self.max_steps + 1):
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise AgentLoopError("timeout", step - 1)
            offered = definitions if step < self.max_steps else []  # the last step must be an answer
            result.steps = step
            try:
                # The request carries the turn's remaining time itself: waiting less is not enough, the thread
                # (and the provider request) would go on after the turn gave up.
                reply = await asyncio.wait_for(asyncio.to_thread(
                    self.model.generate_with_tools, conversation, offered, temperature=self.temperature,
                    max_tokens=self.max_tokens, timeout=remaining), remaining)
            except TimeoutError as exc:
                raise AgentLoopError("timeout", step) from exc
            except Exception as exc:
                # Bodies are never logged; only the failure type.
                logger.warning("agent model call failed error=%s", type(exc).__name__)
                raise AgentLoopError("model", step) from exc
            if reply.tool_calls and offered:
                if turn_trace is not None:
                    turn_trace.tool_rounds += 1
                start = len(conversation)
                conversation.append({"role": "assistant", "content": reply.text, "tool_calls": [
                    {"id": call.id, "name": call.name, "arguments": call.arguments,
                     "provider_data": call.provider_data} for call in reply.tool_calls]})
                # The core runs the batch: reads at once, the rest in order, repeats once, missing arguments named.
                outcomes = await core.run_calls(session, [(call.name, call.arguments) for call in reply.tool_calls])
                for call, outcome in zip(reply.tool_calls, outcomes):
                    if outcome.refused:
                        content = json.dumps(outcome.response)
                    else:
                        result.tools.append(call.name)
                        result.events.extend(outcome.events)
                        content = _result_text(outcome.response)
                    conversation.append({"role": "tool", "tool_call_id": call.id, "content": content})
                result.messages.extend(conversation[start:])
                continue
            text = " ".join((reply.text or "").split()) if reply.text and not reply.tool_calls else ""
            if not text:
                # Tool calls on the last step, or nothing at all: there is no answer to use.
                raise AgentLoopError("empty", step)
            note = validate(reply.text) if validate else None
            if note is None:
                session.note_support(reply.text)
                result.text = reply.text.strip()
                return result
            result.rejections += 1
            conversation += [{"role": "assistant", "content": reply.text}, {"role": "user", "content": note}]
        raise AgentLoopError("rejected", self.max_steps)
