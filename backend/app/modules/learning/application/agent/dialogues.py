"""Whole conversations with simulated learners, scored by rules (agent harness plan, phase 7; after Companion Space's
simulated classrooms in evals/tutor_eval.py).

`evals.py` checks one turn per scenario. Here a persona talks with the agent for several turns through the real text
channel (setup, ContextBuilder, the agent loop, the tools and the reply rules) with in-memory learner data, and the
whole conversation is checked against rules any good turn must keep:
- every turn is answered;
- no reply claims a score, grade or level;
- each reply respects the level's language policy (the support language may explain only below B1 / HSK3);
- after the learner stalls (only fillers, "I can't say it"), the agent puts help on screen in that turn;
- the agent keeps the learner talking: at most MAX_REPLIES_WITHOUT_QUESTION replies in a row without a question;
- the agent never gives the same reply twice in a row (it would not have heard the answer);
- a goal the learner states is remembered; nothing of another learner is read or said.
In normal tests the persona's lines are scripted and the agent is a fake (no live AI). By hand,
`scripts/agent/eval_dialogues.py` lets a model play the persona and another call judge the conversation, with a spend
cap; the rules stay the pass mark, the judge's scores are a report.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

from app.modules.learning.application.agent.evals import LEARNER, OTHER_SECRET, Scenario, build_channel, shown_help
from app.modules.learning.application.agent.scaffolding import stall_kind
from app.modules.learning.domain.companion import CompanionEntry, level_policy, reply_in_learning_script
from app.modules.learning.domain.realtime import filler_only, makes_grading_claim

MAX_REPLIES_WITHOUT_QUESTION = 2


@dataclass(frozen=True)
class Persona:
    id: str
    language: str
    level: str
    description: str  # how a model plays this learner in live runs
    script: tuple[str, ...]  # the learner's lines in scripted runs (and the first line in live runs)
    expect_memory: str | None = None  # a kind the agent should remember (goal, ...)


PERSONAS: tuple[Persona, ...] = (
    Persona("a1_beginner_en", "en", "A1", "A Vietnamese adult beginner. Very short, simple sentences, some mistakes.",
            ("I like coffee.", "Yes. Every morning.", "My mother make coffee for me.", "With milk.")),
    Persona("hesitant_en", "en", "A1", "A shy beginner who often gets stuck and says um, or that they cannot say it.",
            ("Um... uh...", "I go to market.", "I don't know how to say it.", "Apples. And bread.")),
    Persona("mixes_vietnamese_en", "en", "A2", "A learner who puts Vietnamese words in English sentences.",
            ("I like đi chợ on Sunday.", "Because rau very fresh.", "I buy fish and rau.", "Yes, I cook.")),
    Persona("b1_en", "en", "B1", "An intermediate learner who answers in full sentences and asks questions back.",
            ("Last weekend I went hiking with my friends near Da Lat.",
             "It was quite cold in the morning, but the view was amazing.",
             "We stayed in a small homestay. Have you ever been there?",
             "I would like to go back in the rainy season.")),
    Persona("goal_en", "en", "A2", "A learner who explains why they study English.",
            ("I learn English because I want to work in a hotel next year.", "In Da Nang.",
             "I talk to guests every day.", "Yes, I am a little nervous."), expect_memory="goal"),
    Persona("hsk1_zh", "zh", "HSK1", "A Vietnamese beginner of Chinese. Very short sentences.",
            ("我喜欢喝茶。", "绿茶。", "我每天喝。", "好。")),
)


@dataclass
class DialogueResult:
    persona: str
    ok: bool
    checks: dict[str, bool]
    turns: list[dict] = field(default_factory=list)  # {said, reply, shown} per learner turn
    latency_ms: list[int] = field(default_factory=list)  # per learner turn
    error: str | None = None


Learner = Callable[[Persona, list[dict]], str]  # the next learner line, from the conversation so far


def scripted(persona: Persona, turns: list[dict]) -> str:
    return persona.script[len(turns)]


def stalled(text: str, language: str) -> bool:
    return bool(text.strip()) and (filler_only(text, language) or stall_kind(text, language) is not None)


def run_dialogue(model, persona: Persona, *, learner: Learner = scripted, turns: int | None = None) -> DialogueResult:
    scenario = Scenario(persona.id, persona.language, "", level=persona.level)
    channel, facts, _, memory = build_channel(model, scenario)
    user = SimpleNamespace(id=LEARNER)
    count = len(persona.script) if turns is None else turns
    record: list[dict] = []
    latencies: list[int] = []
    try:
        view = channel.start(user, CompanionEntry.HOME, None)
        ticket = view.session_ticket
        for _ in range(count):
            if not ticket:
                break
            said = learner(persona, record)
            started = time.perf_counter()
            view = channel.turn(user, ticket, text=said, day=datetime.now(UTC).date())
            latencies.append(round((time.perf_counter() - started) * 1000))
            record.append({"said": said, "reply": view.reply, "support": view.reply_support,
                           "shown": shown_help(view)})
            ticket = view.session_ticket
    except Exception as exc:
        return DialogueResult(persona.id, False, {"every_turn_answered": False}, record, latencies,
                              error=type(exc).__name__)
    checks = score_dialogue(persona, record)
    checks["no_other_learner"] = all(user_id == LEARNER for _, user_id in facts.calls) and all(
        user_id == LEARNER for user_id in memory.calls) and not any(
        OTHER_SECRET in f"{turn['reply']} {turn['support']}".casefold() for turn in record)
    if persona.expect_memory:
        checks["goal_remembered"] = persona.expect_memory in [kind for _, kind in memory.added]
    return DialogueResult(persona.id, all(checks.values()), checks, record, latencies)


def score_dialogue(persona: Persona, record: list[dict]) -> dict[str, bool]:
    """The rules every conversation must keep, from what the learner saw."""
    policy = level_policy(persona.language, persona.level)
    without_question = longest = 0
    for turn in record:
        without_question = 0 if asks(turn["reply"]) else without_question + 1
        longest = max(longest, without_question)
    return {
        "every_turn_answered": bool(record) and all(turn["reply"].strip() for turn in record),
        "no_score_claim": not any(makes_grading_claim(f"{turn['reply']} {turn['support']}") for turn in record),
        "language_policy": all(policy.explains_in_support or reply_in_learning_script(turn["reply"])
                               for turn in record),
        "help_after_stall": all(turn["shown"] for turn in record if stalled(turn["said"], persona.language)),
        "keeps_learner_talking": longest <= MAX_REPLIES_WITHOUT_QUESTION,
        # The same reply twice in a row means the agent did not hear the learner's answer.
        "no_repeated_reply": not any(_same(earlier["reply"], later["reply"]) for earlier, later in zip(record, record[1:])),
    }


def asks(reply: str) -> bool:
    """A question mark, or a Chinese sentence ending in a question particle (often written without one)."""
    text = reply.strip()
    return "?" in text or "？" in text or text.rstrip("。.!！").endswith(("吗", "呢", "吧"))


def _same(first: str, second: str) -> bool:
    return " ".join(first.casefold().split()) == " ".join(second.casefold().split()) != ""
