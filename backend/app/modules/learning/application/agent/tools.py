"""ToolRegistry: the only functions the agent may call, each checked by the server (TARGET_DESIGN §7).

Three kinds. Read tools return a short, capped result about the learner who is talking, in the language of
the conversation. Display tools only put validated content on the learner's screen. Action tools change data
only through a server check, and anything that changes the learner's data is shown on screen so the learner
can confirm or undo it (a study request can be dismissed; a word is saved only when the learner taps Save; a change
to today's tasks is made at once with an Undo). Action cards (`open_review`, `open_video_region`) only prepare a
screen: the learner taps one button to go there, and nothing navigates by itself.
Every call gets a response; a wrong argument is refused, never fatal. Results are returned with the events the
channel shows the learner, so voice and text share one implementation.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID

from app.modules.activity.contracts import ACTIVITY_KINDS, log_activity
from app.modules.learner.contracts import ERROR_TYPE_CODES, SIGNAL_CODES
from app.modules.learning.application.study_plan import StudyPlanError
from app.modules.learning.application.agent.context import progress_summary
from app.modules.learning.application.agent.session import AgentSession
from app.modules.learning.domain.companion import data_text, lookup_word_allowed
from app.modules.learning.domain.realtime import (
    hint_items,
    valid_correction,
    valid_error_type,
    valid_grammar_explanation,
    valid_hint,
    valid_signal,
    valid_suggestions,
)
from app.modules.learning.domain.roleplay import SCENARIOS, find_scenario, roleplay_instruction

logger = logging.getLogger(__name__)

LOOKUP_TIMEOUT_S = 2.0  # the conversation waits for a read, so a slow store must not hold it up
MAX_ACTIVITY_ROWS = 10
MAX_STUDY_REQUESTS_PER_SESSION = 3
MAX_MEMORIES_PER_SESSION = 3
MEMORY_KINDS = ("goal", "interest", "error", "follow_up")
MAX_MEMORY_CHARS = 200
MAX_REVIEW_WORDS = 20
MAX_TODAY_EDITS_PER_SESSION = 3
PLAN_EDIT_KINDS = ("review", "my_words", "conversation", "video_practice")
MAX_DUE_CARDS = 10
MAX_REGION_ROWS = 200
MAX_REGION_CHARS = 2000
MAX_RECALL_TURNS = 3

Kind = str  # "read" | "display" | "action"


def _string(description: str) -> dict:
    return {"type": "string", "description": description}


@dataclass(frozen=True)
class ToolSpec:
    """A tool as a provider sees it: name, purpose and a JSON schema of its arguments."""

    name: str
    kind: Kind
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


def _object(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, **({"required": required} if required else {})}


_SUGGESTION_LIST = {"type": "array", "description": "Up to three.", "items": _object({
    "sentence": _string("One short sentence in the learning language."),
    "explanation": _string("A short explanation in the support language.")}, ["sentence", "explanation"])}

TOOL_SPECS: tuple[ToolSpec, ...] = (
    # --- read ---
    ToolSpec("get_recent_activity", "read", "Read what the learner recently did in this language (exercises, "
             "lookups, speaking, videos). Short and capped.", _object({
                 "kind": {"type": "string", "description": "Only this kind. Leave out for all.",
                          "enum": sorted(ACTIVITY_KINDS)},
                 "days": {"type": "integer", "description": "How many days back, 1 for since yesterday."},
                 "limit": {"type": "integer", "description": "How many, at most 10."}})),
    ToolSpec("get_progress_summary", "read", "Counts of what the learner did in the last days, by kind.",
             _object({"days": {"type": "integer", "description": "How many days back, at most 30."}})),
    ToolSpec("get_region", "read", "The video part the learner is studying and their results in it, with the ids "
             "open_video_region takes."),
    ToolSpec("get_due_cards", "read", "A few words due for review in this language, each with the id open_review "
             "takes and, when known, how far the learner has got with it (use): bring a word back in a way one step "
             "beyond that."),
    ToolSpec("get_study_requests", "read", "The practice already given to the learner and still open."),
    ToolSpec("get_grammar_lesson", "read", "One approved grammar lesson.", _object({
        "grammar_point": _string("A key from the reference grammar points.")}, ["grammar_point"])),
    ToolSpec("lookup_word", "read", "Look up the dictionary meaning of a word the learner asked about.", _object({
        "word": _string("The word exactly as the learner said it.")}, ["word"])),
    ToolSpec("recall", "read", "Read again what the learner said in an earlier conversation that one thing you remember "
             "came from, when its details matter now. Only for a remembered item marked (recall).", _object({
                 "id": _string("The id of the remembered item.")}, ["id"])),
    # --- display ---
    ToolSpec("show_hint", "display", "Show the learner a hint for answering your last question.", _object({
        "question": _string("A guiding question in the support language."),
        "words": {"type": "array", "items": {"type": "string"},
                  "description": "Up to three of the listed words the learner could use."},
        "frame": _string("A sentence frame in the learning language with ___ for the learner's words."),
        "frame_reason": _string("Why the frame works, in the support language."),
        "model_sentence": _string("One model answer in the learning language.")}, ["question"])),
    ToolSpec("show_correction", "display", "Show the learner a correction of what they just said.", _object({
        "quote": _string("The learner's words, copied exactly from what they just said."),
        "suggestion": _string("The corrected form."),
        "note": _string("A short note in the support language inviting them to try again."),
        "error_type": {"type": "string", "description": "The kind of grammar mistake, when it is one of these.",
                       "enum": sorted(ERROR_TYPE_CODES)},
        "grammar_point": _string("A key from the reference grammar points when the mistake is exactly that point.")},
        ["quote", "suggestion", "note"])),
    ToolSpec("explain_grammar", "display", "Explain the grammar of the learner's last sentence.",
             _object({"explanation": _string("The rule in a few short sentences, in the support language."),
                      "example": _string("One short example sentence in the learning language."),
                      "grammar_point": _string("A key from the reference grammar points, only when it is exactly "
                                               "the rule. Leave out otherwise.")}, ["explanation"])),
    ToolSpec("show_natural", "display", "Show more natural ways to say the learner's last sentence.",
             _object({"options": _SUGGESTION_LIST}, ["options"])),
    ToolSpec("show_suggestions", "display", "Show the learner a few things they could say next.",
             _object({"suggestions": _SUGGESTION_LIST}, ["suggestions"])),
    ToolSpec("show_tasks", "display", "Show the learner what they could do today. Once, right after your greeting."),
    # --- action ---
    ToolSpec("save_word", "action", "Offer to save a word you looked up to the learner's notebook; they confirm.",
             _object({"word": _string("The word as you looked it up.")}, ["word"])),
    ToolSpec("create_study_request", "action", "Ask the learner to practise one grammar point or word again; it "
             "appears in their notebook. At most three per conversation; the server checks the item exists.", _object({
                 "kind": {"type": "string", "enum": ["grammar_redo", "word_review"]},
                 "item": _string("For grammar_redo a key from the reference grammar points; for word_review the id "
                                 "of a word from the app's list."),
                 "reason": _string("One short reason in the support language.")}, ["kind", "item"])),
    ToolSpec("start_roleplay", "action", "Start a roleplay here, when the learner asks for one.", _object({
        "scenario": {"type": "string", "description": "The situation.", "enum": sorted(item.id for item in SCENARIOS)},
        "swap_roles": {"type": "boolean", "description": "True when the learner wants the other role."}},
        ["scenario"])),
    ToolSpec("offer_activity", "action", "Show a button to another screen, when the learner asks for that activity.",
             _object({"kind": {"type": "string", "enum": ["grammar", "notebook", "review"]}}, ["kind"])),
    ToolSpec("open_review", "action", "Prepare a review of exactly these words and show the learner a button that "
             "opens it. Only when the learner wants to review now. Use ids from get_due_cards; the server keeps only "
             "the learner's own saved words.", _object({
                 "concept_ids": {"type": "array", "items": {"type": "string"},
                                 "description": "Up to 20 word ids from get_due_cards."}}, ["concept_ids"])),
    ToolSpec("open_video_region", "action", "Show the learner a button that opens their own video at a part of it. "
             "Only when they want to go there. Use the ids from get_region; never invent one.", _object({
                 "library_item_id": _string("The id of the learner's video, from get_region."),
                 "region_id": _string("The id of the video part, from get_region.")},
                 ["library_item_id", "region_id"])),
    ToolSpec("edit_today", "action", "Add or remove one task of the learner's tasks for today, when they ask for it. "
             "It is done at once and the learner sees it with an Undo. At most three changes per conversation.",
             _object({"change": {"type": "string", "enum": ["add", "remove"]},
                      "kind": {"type": "string", "enum": list(PLAN_EDIT_KINDS),
                               "description": "review: the words due; my_words: practise saved words; conversation: "
                                              "talk with you; video_practice: practise a video."},
                      "library_item_id": _string("The learner's video, only for video_practice or a talk about a "
                                                 "video; from get_region.")}, ["change", "kind"])),
    ToolSpec("note_interest", "action", "Quietly note a topic the learner said they like. Never shown.", _object({
        "topic": {"type": "string", "description": "The closest topic group.",
                  "enum": sorted(SIGNAL_CODES["topic"])}}, ["topic"])),
    ToolSpec("note_goal", "action", "Quietly note what the learner said they are learning for. Never shown.", _object({
        "goal": {"type": "string", "description": "The closest goal.", "enum": sorted(SIGNAL_CODES["goal"])}},
        ["goal"])),
    ToolSpec("remember", "action", "Quietly keep one lasting fact about the learner for later conversations. Never "
             "shown. At most three per conversation.", _object({
                 "kind": {"type": "string", "description": "goal: what they are learning for; interest: something they "
                          "like; error: a mistake they keep making; follow_up: something you promised to do next time.",
                          "enum": list(MEMORY_KINDS)},
                 "text": _string("One short sentence in the support language, at most 200 characters.")},
                 ["kind", "text"])),
    ToolSpec("forget", "action", "Remove one thing you remember, when the learner asks you to forget it. Use the id "
             "shown beside it in what you remember.", _object({
                 "id": _string("The id of the remembered item.")}, ["id"])),
)


# Only the text channel declares this one: the voice channel has no screen element for it.
TEXT_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("suggest_practice", "display", "Suggest one practice tool on one line of the video part, only when the "
             "learner could not hear or catch that line (dictation) or wants to say it better (shadowing).", _object({
                 "tool": {"type": "string", "enum": ["dictation", "shadowing"]},
                 "segment_ref": _string("The line's reference, s1, s2, ... as listed in the video part."),
                 "reason": _string("Why it helps, briefly, in the support language.")},
                 ["tool", "segment_ref", "reason"])),
)


@dataclass
class ToolResult:
    """What the model gets back, and what the channel shows the learner (validated content only)."""

    response: dict
    events: list[dict] = field(default_factory=list)
    correction: dict | None = None  # a shown correction, for the learner's kept transcript (FR-3.11)
    refused: bool = False  # the call did not run (AgentCore: not offered, over a limit, arguments missing)


def _text(value) -> str | None:
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else None


def _int(value, *, low: int, high: int, default: int) -> int:
    return min(max(value, low), high) if isinstance(value, int) and not isinstance(value, bool) else default


class ToolRegistry:
    def __init__(self, *, facts=None, word_lookup=None, tasks=None, learning_log=None, memory=None,
                 plan=None, video_regions=None, transcripts=None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.facts = facts  # AgentFacts: the learner's own data; None = nothing to read
        self.word_lookup = word_lookup
        self.tasks = tasks  # (user, day) -> today's open plan items
        self.learning_log = learning_log
        self.memory = memory  # AgentMemory: what the agent remembers across conversations; None = nothing kept
        self.plan = plan  # TodayPlanEditor: add or remove one of today's tasks; None = not wired
        self.video_regions = video_regions  # VideoRegionChecker; None = a video region cannot be opened
        self.transcripts = transcripts  # the learner's kept turns (FR-3.11) that memory rows point to; None = no recall
        self.clock = clock
        self._handlers = {spec.name: getattr(self, "_" + spec.name) for spec in (*TOOL_SPECS, *TEXT_TOOL_SPECS)}

    @staticmethod
    def specs(*, text: bool = False) -> tuple[ToolSpec, ...]:
        return (*TOOL_SPECS, *TEXT_TOOL_SPECS) if text else TOOL_SPECS

    async def call(self, session: AgentSession, name: str, args) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult({"error": "unknown function"})
        try:
            result = await handler(session, args if isinstance(args, dict) else {})
        except (TypeError, ValueError, AttributeError) as exc:
            logger.warning("agent tool arguments rejected tool=%s error=%s", name, type(exc).__name__)
            return ToolResult({"error": "invalid arguments"})
        if result.response.get("shown") is False and "error" not in result.response:
            session.rejected_calls += 1
        return result

    async def _read(self, label: str, read, scale: float = 1.0):
        """A blocking read in a thread with a deadline; None when it failed or was slow."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(read), LOOKUP_TIMEOUT_S * scale)
        except Exception as exc:
            logger.warning("agent read unavailable tool=%s error=%s", label, type(exc).__name__)
            return None

    # --- Read ----------------------------------------------------------------------------------

    async def _get_recent_activity(self, session: AgentSession, args: dict) -> ToolResult:
        if self.facts is None:
            return ToolResult({"found": False})
        limit = _int(args.get("limit"), low=1, high=MAX_ACTIVITY_ROWS, default=MAX_ACTIVITY_ROWS)
        kind = args.get("kind") if isinstance(args.get("kind"), str) and args.get("kind") in ACTIVITY_KINDS else None
        days = args.get("days")
        since = (self.clock() - timedelta(days=_int(days, low=1, high=30, default=1))
                 if isinstance(days, int) and not isinstance(days, bool) else None)
        ticket = session.ticket
        rows = await self._read("get_recent_activity", lambda: self.facts.recent_activity(
            session.user.id, ticket.language_code, kind=kind, since=since, limit=limit))
        if rows is None:
            return ToolResult({"found": False})
        return ToolResult({"found": bool(rows), "activity": rows[:limit]})

    async def _get_progress_summary(self, session: AgentSession, args: dict) -> ToolResult:
        if self.facts is None:
            return ToolResult({"found": False})
        days = _int(args.get("days"), low=1, high=30, default=7)
        since = self.clock() - timedelta(days=days)
        rows = await self._read("get_progress_summary", lambda: self.facts.recent_activity(
            session.user.id, session.ticket.language_code, kind=None, since=since, limit=MAX_REGION_ROWS))
        if rows is None:
            return ToolResult({"found": False})
        return ToolResult({"found": bool(rows), **progress_summary(rows, days=days)})

    async def _get_region(self, session: AgentSession, args: dict) -> ToolResult:
        ticket = session.ticket
        region_id = getattr(ticket, "region_id", None)
        if not ticket.region_lines or not ticket.excerpt:
            return ToolResult({"found": False})
        found = {"found": True, "lines": ticket.excerpt[:MAX_REGION_CHARS]}
        library_item_id = getattr(ticket, "library_item_id", None)
        if region_id and library_item_id:
            found.update(library_item_id=str(library_item_id), region_id=region_id)
        if self.facts is not None and region_id:
            rows = await self._read("get_region", lambda: self.facts.region_activity(
                session.user.id, region_id, limit=MAX_REGION_ROWS))
            if rows:
                found["results"] = progress_summary(rows, days=0)["by_kind"]
        return ToolResult(found)

    async def _get_due_cards(self, session: AgentSession, args: dict) -> ToolResult:
        if self.facts is None:
            return ToolResult({"found": False})
        cards = await self._read("get_due_cards", lambda: self.facts.due_cards(
            session.user.id, session.ticket.language_code, limit=MAX_DUE_CARDS))
        due = await self._read("get_due_cards", lambda: self.facts.due_counts(session.user.id))
        if cards is None:
            return ToolResult({"found": False})
        return ToolResult({"found": bool(cards), "cards": cards[:MAX_DUE_CARDS], "due_by_language": due or {}})

    async def _get_study_requests(self, session: AgentSession, args: dict) -> ToolResult:
        if self.facts is None:
            return ToolResult({"found": False})
        rows = await self._read("get_study_requests", lambda: self.facts.study_requests(
            session.user.id, session.ticket.language_code, limit=MAX_ACTIVITY_ROWS))
        if rows is None:
            return ToolResult({"found": False})
        return ToolResult({"found": bool(rows), "requests": rows[:MAX_ACTIVITY_ROWS]})

    async def _get_grammar_lesson(self, session: AgentSession, args: dict) -> ToolResult:
        card = session.lesson_menu.card(args.get("grammar_point")) if session.lesson_menu else None
        if card is None:
            return ToolResult({"found": False})
        return ToolResult({"found": True, "title": card["title"], "summary": card["explanation"][:600],
                           "rules": [str(rule)[:200] for rule in card["rules"][:4]], "example": card["example"]})

    async def _lookup_word(self, session: AgentSession, args: dict) -> ToolResult:
        ticket = session.ticket
        allowed = lookup_word_allowed(_text(args.get("word")), session.learner_said(), ticket.items,
                                      ticket.language_code)
        if self.word_lookup is None or allowed is None:
            return ToolResult({"found": False})
        found = await self._read("lookup_word", lambda: self.word_lookup.lookup(
            allowed, language_code=ticket.language_code))
        entries = [entry for entry in (found or []) if entry.senses][:2]
        if not entries:
            return ToolResult({"found": False})
        session.looked_up[allowed.casefold()] = entries
        self.record_lookup(session, allowed)
        event = {"type": "looked_up", "word": allowed, "entries": [{
            "headword": entry.headword,
            "senses": [{"text": sense.text, "part_of_speech": sense.part_of_speech} for sense in entry.senses[:3]],
            "source_name": entry.source_name, "source_license": entry.source_license, "source_url": entry.source_url,
        } for entry in entries]}
        # The model sees the dictionary text as data in the function response.
        return ToolResult({"found": True, "entries": [{"headword": entry.headword[:60],
                                                       "senses": [sense.text[:120] for sense in entry.senses[:3]]}
                                                      for entry in entries]}, [event])

    async def _recall(self, session: AgentSession, args: dict) -> ToolResult:
        """The learner's own kept turns one remembered row came from (its evidence); only rows the agent was shown,
        only this learner's turns, nothing once the turns were deleted or the consents withdrawn."""
        wanted = _text(args.get("id"))
        row = next((row for row in (session.context.memory if session.context else ())
                    if wanted and str(row.get("id")) == wanted), None)
        refs = []
        for item in (row or {}).get("evidence") or []:
            try:
                refs.append((UUID(str(item["session_id"])), int(item["turn_index"])))
            except (KeyError, TypeError, ValueError):
                continue
        if self.transcripts is None or not refs:
            return ToolResult({"found": False})
        turns = await self._read("recall", lambda: self.transcripts.recall(session.user.id, refs[:MAX_RECALL_TURNS]))
        if not turns:
            return ToolResult({"found": False})
        return ToolResult({"found": True, "turns": [{
            "when": turn.get("when"), "learner_said": data_text(str(turn.get("said") or ""))[:300],
            "you_said": data_text(str(turn.get("you_said") or ""))[:300]} for turn in turns[:MAX_RECALL_TURNS]]})

    def record_lookup(self, session: AgentSession, word: str) -> None:
        """A lookup is a learning fact: one log row."""
        ticket = session.ticket
        log_activity(self.learning_log, user_id=session.user.id, language_code=ticket.language_code,
                     client_event_id=f"lookup:{session.id}:{word.casefold()[:60]}", kind="lookup", outcome="done",
                     source_type="agent_session", source_id=str(session.id), detail={"text": word[:80]})

    # --- Display -------------------------------------------------------------------------------

    async def _show_hint(self, session: AgentSession, args: dict) -> ToolResult:
        ticket = session.ticket
        words = args.get("words")
        items = hint_items([word for word in words if isinstance(word, str)] if isinstance(words, list) else [],
                           ticket.items)
        # PRD 8.12: the agent chooses what the hint gives; its step is named from what it holds, for the screen.
        fields = {key: _text(args.get(key)) for key in ("question", "frame", "frame_reason", "model_sentence")}
        if not fields["question"]:
            return ToolResult({"shown": False, "reason": "question is required"})
        if not valid_hint(question=fields["question"], frame=fields["frame"], frame_reason=fields["frame_reason"],
                          model_sentence=fields["model_sentence"], language_code=ticket.language_code):
            return ToolResult({"shown": False, "reason": "invalid hint: each field at most 300 characters, a frame "
                                                         "needs ___ and frame_reason, the model sentence is in the learning language "
                                                         "and gives no score"})
        level = 3 if fields["model_sentence"] else 2 if fields["frame"] else 1
        session.scaffolding.hint_shown(level)
        auto, session.auto_hint_pending = session.auto_hint_pending, False
        event = {"type": "hint", "level": level, **fields, "auto": auto,
                 "items": [{"id": item.item_id, "text": item.text, "meaning": item.meaning} for item in items]}
        session.hints += 1
        session.reuse_words.extend(item.text for item in items if item.text not in session.reuse_words)
        if session.tracks:
            session.assisted_ids.update(UUID(item.item_id) for item in items)
        for text in fields.values():
            session.note_support(text)
        return ToolResult({"shown": True, "words_shown": [item.text for item in items]}, [event])

    async def _show_suggestions(self, session: AgentSession, args: dict) -> ToolResult:
        items = valid_suggestions(args.get("suggestions"), session.ticket.language_code)
        if not items:
            return ToolResult({"shown": False})
        session.suggestions += 1
        for item in items:
            session.note_support(item["sentence"])
        return ToolResult({"shown": True}, [{"type": "suggestions", "items": items}])

    async def _show_natural(self, session: AgentSession, args: dict) -> ToolResult:
        items = valid_suggestions(args.get("options"), session.ticket.language_code)
        if not items:
            return ToolResult({"shown": False})
        for item in items:
            session.note_support(item["sentence"])
        return ToolResult({"shown": True}, [{"type": "natural", "items": items}])

    async def _explain_grammar(self, session: AgentSession, args: dict) -> ToolResult:
        lesson = session.lesson_menu.card(args.get("grammar_point")) if session.lesson_menu else None
        if lesson:
            # The agent only named a point; what the learner reads is the lesson the owner approved for it.
            session.note_support(lesson["example"])
            return ToolResult({"shown": True}, [{"type": "grammar", **lesson}])
        shown = valid_grammar_explanation(args.get("explanation"), args.get("example"), session.ticket.language_code)
        if not shown:
            return ToolResult({"shown": False})
        session.note_support(shown[1])
        # AI-written, not from a checked grammar entry.
        return ToolResult({"shown": True}, [{"type": "grammar", "explanation": shown[0], "example": shown[1],
                                             "unverified": True}])

    async def _show_correction(self, session: AgentSession, args: dict) -> ToolResult:
        quote, suggestion, note = (_text(args.get(key)) or "" for key in ("quote", "suggestion", "note"))
        if not valid_correction(quote=quote, suggestion=suggestion, note=note, learner_said=session.learner_said()):
            return ToolResult({"shown": False})
        session.corrections += 1
        kind = valid_error_type(args.get("error_type"))
        if kind and kind not in session.error_codes:
            session.error_codes.append(kind)  # the kind only, unless the learner allowed transcripts
        session.note_support(suggestion)
        events = [{"type": "correction", "quote": quote, "suggestion": suggestion, "note": note}]
        response: dict = {"shown": True}
        point = args.get("grammar_point")
        if isinstance(point, str) and session.lesson_menu and point in session.lesson_menu.lessons:
            outcome, event = await self._grammar_redo(session, point, f"{quote} → {suggestion}")
            response["study_request"] = outcome
            events += [event] if event else []
        return ToolResult(response, events, correction={"quote": quote, "suggestion": suggestion,
                                                        "note": note or None, "error_type": kind})

    async def _grammar_redo(self, session: AgentSession, point: str, reason: str) -> tuple[str, dict | None]:
        """A corrected mistake on an approved grammar point becomes practice in the notebook (PRD 8.10)."""
        if point in session.redo_points:
            return "exists", None
        if self.facts is None or session.study_requests >= MAX_STUDY_REQUESTS_PER_SESSION:
            return "not_created", None
        ticket = session.ticket
        outcome = await self._read("create_study_request", lambda: self.facts.create_request(
            session.user.id, ticket.language_code, ticket.support_language_code, kind="grammar_redo",
            item_id=point, reason=reason[:300]))
        if outcome not in ("created", "exists"):
            return "not_created", None
        session.redo_points.add(point)
        if outcome != "created":
            return "exists", None
        session.study_requests += 1
        title = session.lesson_menu.lessons[point][0] if session.lesson_menu else point
        return "created", {"type": "study_request", "kind": "grammar_redo", "item": point, "title": title}

    async def _suggest_practice(self, session: AgentSession, args: dict) -> ToolResult:
        """Only a line this conversation offered counts; the learner decides whether to open the tool."""
        tool, ref, reason = args.get("tool"), args.get("segment_ref"), _text(args.get("reason"))
        line = next((item for item in session.ticket.region_lines if item.ref == ref), None)
        if tool not in ("dictation", "shadowing") or line is None or reason is None:
            return ToolResult({"shown": False})
        return ToolResult({"shown": True}, [{
            "type": "practice_suggestion", "tool": tool, "segment_id": line.segment_id, "start_ms": line.start_ms,
            "end_ms": line.end_ms, "reason": reason[:200]}])

    async def _show_tasks(self, session: AgentSession, args: dict) -> ToolResult:
        if self.tasks is None or session.tasks_shown:
            return ToolResult({"shown": False})
        items = await self._read("show_tasks", lambda: self.tasks(session.user, session.day), 2)
        if items is None:  # a failed read leaves the tasks to show later
            return ToolResult({"shown": False})
        session.tasks_shown = True
        return ToolResult({"shown": True, "tasks": [item["kind"] for item in items]},
                          [{"type": "tasks", "items": items}])

    # --- Action --------------------------------------------------------------------------------

    async def _save_word(self, session: AgentSession, args: dict) -> ToolResult:
        """Only a word looked up in this conversation, one dictionary sense; the learner taps Save to keep it."""
        word = _text(args.get("word"))
        entries = session.looked_up.get(word.casefold()) if word else None
        entry = next((item for item in entries or [] if item.entry_id is not None and item.senses
                      and item.senses[0].sense_id), None)
        if entry is None:
            return ToolResult({"offered": False})
        sense = entry.senses[0]
        return ToolResult({"offered": True}, [{
            "type": "save_word", "word": word, "headword": entry.headword, "language_code": session.ticket.language_code,
            "entry_id": str(entry.entry_id), "sense_id": sense.sense_id, "meaning": sense.text[:120]}])

    async def _create_study_request(self, session: AgentSession, args: dict) -> ToolResult:
        """Ask the learner to practise one grammar point or word again. The server checks it exists."""
        kind, item = args.get("kind"), _text(args.get("item"))
        if (self.facts is None or kind not in ("grammar_redo", "word_review") or item is None
                or len(item) > 120 or session.study_requests >= MAX_STUDY_REQUESTS_PER_SESSION):
            return ToolResult({"created": False})
        reason = _text(args.get("reason"))
        ticket = session.ticket
        try:
            outcome = await asyncio.wait_for(asyncio.to_thread(
                self.facts.create_request, session.user.id, ticket.language_code, ticket.support_language_code,
                kind=kind, item_id=item, reason=reason[:300] if reason else None), LOOKUP_TIMEOUT_S)
        except Exception as exc:
            logger.warning("study request unavailable error=%s", type(exc).__name__)
            return ToolResult({"created": False})
        events = []
        if outcome == "created":
            session.study_requests += 1
            title = (session.lesson_menu.lessons[item][0]
                     if kind == "grammar_redo" and session.lesson_menu and item in session.lesson_menu.lessons else None)
            events.append({"type": "study_request", "kind": kind, "item": item, "title": title})
        return ToolResult({"created": outcome == "created", "already_open": outcome == "exists"}, events)

    async def _start_roleplay(self, session: AgentSession, args: dict) -> ToolResult:
        scenario = find_scenario(_text(args.get("scenario")))
        if scenario is None:
            return ToolResult({"started": False})
        swap = args.get("swap_roles") is True
        support = session.ticket.support_language_code
        session.start_roleplay()
        self.log_roleplay(session, scenario.id, swap)
        return ToolResult({"started": True, "instruction": roleplay_instruction(scenario.id, swap)},
                          [{"type": "roleplay", "title": scenario.title[1 if support == "vi" else 2 if support == "zh"
                                                                        else 0]}])

    def log_roleplay(self, session: AgentSession, scenario_id: str, swap_roles: bool) -> None:
        log_activity(self.learning_log, user_id=session.user.id, language_code=session.ticket.language_code,
                     client_event_id=f"roleplay:{session.id}:{scenario_id}", kind="roleplay", outcome="done",
                     source_type="agent_session", source_id=str(session.id),
                     detail={"scenario": scenario_id, "swap_roles": swap_roles})

    async def _open_review(self, session: AgentSession, args: dict) -> ToolResult:
        """A review over exactly the words the agent named, kept only when they are this learner's saved words."""
        raw = args.get("concept_ids")
        ids: list[UUID] = []
        for value in raw if isinstance(raw, list) else []:
            try:
                parsed = UUID(value.strip()) if isinstance(value, str) else None
            except ValueError:
                parsed = None
            if parsed is not None and parsed not in ids:
                ids.append(parsed)
        if self.facts is None or not ids:
            return ToolResult({"opened": False})
        ids = ids[:MAX_REVIEW_WORDS]
        language = session.ticket.language_code
        owned = await self._read("open_review", lambda: self.facts.owned_saved_ids(session.user.id, language, ids))
        asked = {str(item) for item in ids}
        kept = [value for value in owned or [] if value in asked][:MAX_REVIEW_WORDS]
        if not kept:
            return ToolResult({"opened": False})
        return ToolResult({"opened": True, "words": len(kept), "dropped": len(ids) - len(kept)}, [{
            "type": "action", "action": "open_review", "language_code": language, "concept_ids": kept}])

    async def _open_video_region(self, session: AgentSession, args: dict) -> ToolResult:
        """The learner's own video at a well-formed part of it; the learner taps the button to go there."""
        try:
            raw_item = args.get("library_item_id")
            library_item_id = UUID(raw_item.strip()) if isinstance(raw_item, str) else None
        except ValueError:
            library_item_id = None
        region = _text(args.get("region_id"))
        if self.video_regions is None or library_item_id is None or region is None or len(region) > 80:
            return ToolResult({"opened": False})
        target = await self._read("open_video_region", lambda: self.video_regions.check(
            session.user.id, library_item_id, region))
        if target is None:
            return ToolResult({"opened": False})
        return ToolResult({"opened": True}, [{
            "type": "action", "action": "open_video_region", "library_item_id": str(library_item_id),
            "region_id": region.lower(), "title": target.title, "start_ms": target.start_ms}])

    async def _edit_today(self, session: AgentSession, args: dict) -> ToolResult:
        """Adds or removes one of today's tasks at once; the learner sees it with an Undo for exactly this change."""
        change, kind = args.get("change"), args.get("kind")
        try:
            raw_item = args.get("library_item_id")
            library_item_id = UUID(raw_item.strip()) if isinstance(raw_item, str) and raw_item.strip() else None
        except ValueError:
            return ToolResult({"edited": False, "reason": "invalid"})
        if self.plan is None or session.day is None:
            return ToolResult({"edited": False, "reason": "unavailable"})
        if change not in ("add", "remove") or kind not in PLAN_EDIT_KINDS:
            return ToolResult({"edited": False, "reason": "invalid"})
        if session.today_edits >= MAX_TODAY_EDITS_PER_SESSION:
            return ToolResult({"edited": False, "reason": "limit"})
        try:
            edit_item = self.plan.add_item if change == "add" else self.plan.remove_item
            edit = await asyncio.wait_for(asyncio.to_thread(
                edit_item, session.user, session.day, kind=kind, library_item_id=library_item_id),
                LOOKUP_TIMEOUT_S * 3)
        except StudyPlanError as exc:
            return ToolResult({"edited": False, "reason": exc.code})
        except Exception as exc:
            logger.warning("today edit unavailable error=%s", type(exc).__name__)
            return ToolResult({"edited": False, "reason": "unavailable"})
        session.today_edits += 1
        return ToolResult({"edited": True, "change": edit.change, "kind": edit.kind}, [{
            "type": "action", "action": "today_edited", "change": edit.change, "item_id": str(edit.item_id),
            "kind": edit.kind, "minutes": edit.minutes, "title": edit.video_title}])

    async def _offer_activity(self, session: AgentSession, args: dict) -> ToolResult:
        kind = args.get("kind")
        if kind not in ("review", "grammar", "notebook"):
            return ToolResult({"shown": False})
        return ToolResult({"shown": True}, [{"type": "offer", "kind": kind}])

    async def _note_interest(self, session: AgentSession, args: dict) -> ToolResult:
        return self._note(session, "topic", args.get("topic"))

    async def _note_goal(self, session: AgentSession, args: dict) -> ToolResult:
        return self._note(session, "goal", args.get("goal"))

    @staticmethod
    def _note(session: AgentSession, kind: str, code) -> ToolResult:
        # Quiet notes for personalization: a closed code or nothing, never shown to the learner.
        noted = valid_signal(kind, code)
        if noted is not None:
            bucket = session.interests if kind == "topic" else session.goals
            if noted[1] not in bucket:
                bucket.append(noted[1])
        return ToolResult({"noted": noted is not None})

    async def _remember(self, session: AgentSession, args: dict) -> ToolResult:
        """A lasting fact the learner stated, as one short sentence; quiet, never shown, at most three a conversation."""
        kind, text = args.get("kind"), _text(args.get("text"))
        if (self.memory is None or kind not in MEMORY_KINDS or text is None
                or session.memories >= MAX_MEMORIES_PER_SESSION):
            return ToolResult({"remembered": False})
        text = text[:MAX_MEMORY_CHARS]
        # What lasts for every language (a goal, an interest) is kept without one; a mistake or a promise belongs to
        # the language of this conversation.
        language = session.ticket.language_code if kind in ("error", "follow_up") else None
        if session.defer_memory:  # written by `commit_memory` once the turn is spent
            session.memory_ops.append(("add", kind, text, language))
            session.memories += 1
            return ToolResult({"remembered": True})
        stored = await self._read("remember", lambda: self.memory.add(
            session.user.id, kind=kind, text=text, language_code=language))
        if stored is not True:
            return ToolResult({"remembered": False})
        session.memories += 1
        return ToolResult({"remembered": True})

    async def _forget(self, session: AgentSession, args: dict) -> ToolResult:
        """Removes one of this learner's own rows by the id the agent was shown; another id removes nothing."""
        raw = args.get("id")
        try:
            memory_id = UUID(raw.strip()) if isinstance(raw, str) else None
        except ValueError:
            memory_id = None
        if self.memory is None or memory_id is None:
            return ToolResult({"forgotten": False})
        if session.defer_memory:  # only a row the agent was shown can be forgotten; removed once the turn is spent
            shown = {str(row["id"]) for row in (session.context.memory if session.context else ())}
            if str(memory_id) not in shown:
                return ToolResult({"forgotten": False})
            session.memory_ops.append(("forget", memory_id))
            return ToolResult({"forgotten": True})
        removed = await self._read("forget", lambda: self.memory.delete_one(session.user.id, memory_id))
        return ToolResult({"forgotten": removed is True})

    async def commit_memory(self, session: AgentSession) -> None:
        """Writes what the agent remembered or forgot in a turn that has been spent; a failed write is dropped (memory
        never fails a conversation) and nothing stays queued."""
        operations, session.memory_ops = session.memory_ops, []
        for operation in operations:
            if operation[0] == "add":
                _, kind, text, language = operation
                await self._read("remember", partial(self.memory.add, session.user.id, kind=kind, text=text,
                                                     language_code=language))
            else:
                await self._read("forget", partial(self.memory.delete_one, session.user.id, operation[1]))
