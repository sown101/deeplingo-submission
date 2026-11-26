"""The agent's text channel: one turn per request; the conversation is kept on the server between requests.

Flow: start (entry point + selectors -> server-built context, opening turn, signed ticket) -> turn (WAV or typed
text + ticket -> the agent loop -> synthesised reply, new ticket) -> finish. The ticket is only a signed, single-use
reference to the conversation; its state (`TextSession`: context, the loop's messages with earlier tool results,
the help shown, counters, evidence) is in a `SessionStore` and is deleted when the conversation finishes. A store
failure is "unavailable", never a new conversation. The loop is the core's (loop.py): one
system prompt, the conversation as messages, the registry's tools called natively; the agent may help unasked
(PRD 8.12). Hesitation (only fillers, or "I can't say it") reaches the agent as an event and it chooses the help;
a correction on an approved grammar point becomes a `grammar_redo` study request inside the tool. What the tools
put on screen becomes the turn's fields. Audio stays transient. This is the channel the web uses
(`/learner/me/companion/*`) when the microphone or live voice is unavailable.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from functools import wraps
from uuid import UUID

from app.modules.activity.contracts import log_activity
from app.modules.learning.application.agent.choices import opening_choices, starts_open
from app.modules.learning.application.agent.context import ContextBuilder, practice_lines
from app.modules.learning.application.agent.core import AgentCore, split_reply
from app.modules.learning.application.agent.conversation import (
    MAX_KEPT_LEARNER_TURNS,
    MAX_WEAK_WORDS,
    MemorySessionStore,
    TextSession,
    dump_state,
    load_state,
    seconds_until,
)
from app.modules.learning.application.agent.ports import (
    CompanionTicket,
    CompanionTicketCodec,
    InvalidCompanionTicket,
    SessionStore,
    SessionStoreUnavailable,
    SessionToken,
    SpeechSynthesisUnavailable,
    SpeechSynthesizer,
)
from app.modules.learning.application.agent.history import compact as compact_history
from app.modules.learning.application.agent.loop import AgentLoop, AgentLoopError, LoopResult
from app.modules.learning.application.agent.pace import observe as observe_pace
from app.modules.learning.application.agent.pace import pace_note
from app.modules.learning.application.agent.prompts import (
    OPEN_START_CUE,
    START_CUE,
    build_agent_system_prompt,
    grammar_points_block,
    hesitation_event,
    learner_request,
)
from app.modules.learning.application.agent.scaffolding import stall_kind
from app.modules.learning.application.agent.setup import EXPIRED, UNAVAILABLE, ConversationSetup, PreparedConversation
from app.modules.learning.application.agent.tools import ToolRegistry, ToolSpec
from app.modules.learning.application.agent.trace import CompanionTrace, traced
from app.modules.learning.application.agent.views import (
    CompanionActionView,
    CompanionChoiceView,
    CompanionAudioView,
    CompanionCorrectionView,
    CompanionFinishView,
    CompanionFrameView,
    CompanionGrammarView,
    CompanionHintsView,
    CompanionItemView,
    CompanionOptionView,
    CompanionPracticeSuggestionView,
    CompanionSenseView,
    CompanionStudyRequestView,
    CompanionTurnView,
    CompanionWordView,
)
from app.modules.learning.application.conversation_pronunciation import (
    MAX_SCORED_TURNS, MAX_TURN_AUDIO_MS, MAX_TURN_TEXT_CHARS, weak_words,
)
from app.modules.learning.application.session_events import LearnerTurn, SelectedWord, SessionText
from app.modules.learning.application.shadowing import provider_failure_error
from app.modules.learning.application.speaking_ports import (
    NoSpeechDetected,
    SpeakingPracticeError,
    SpeechProviderFailure,
)
from app.modules.learning.application.speech_transcription import SpeechTranscriber
from app.modules.learning.application.spoken_words import saved_word_targets, turns_with_server_support
from app.modules.learning.domain.companion import (
    MAX_HELP_REQUESTS,
    MAX_HISTORY_MESSAGES,
    MAX_TURNS,
    CompanionItem,
    CompanionMessage,
    clip_message,
    data_text,
    level_policy,
    reply_in_learning_script,
)
from app.modules.learning.domain.realtime import clean_transcript
from app.modules.learning.domain.roleplay import roleplay_instruction
from app.modules.learning.domain.speaking import HintMatcher, spoken_unit_count, used_hint_ids
from app.modules.learning.domain.speech_audio import SpeechAudio, audio_quality_issues, voice_activity
from app.platform.llm.port import ToolCallingModel
from app.platform.llm.usage import usage_scope
from app.platform.observability.port import NoopTracing, TurnTracing, trace_turn

logger = logging.getLogger(__name__)

MAX_TYPED_CHARS = 300
HELP_REQUESTS = ("hint", "explain", "natural", "suggest")  # the help buttons, as on the voice screen
# What the agent may call on this channel. The rest of the registry needs the voice channel or a screen element
# the web does not have (offers, saving a word, roleplay switch, quiet notes) or is decided later (PRD 8.12 point 4).
TEXT_TOOLS = ("get_recent_activity", "get_progress_summary", "get_region", "get_due_cards", "get_study_requests",
              "get_grammar_lesson", "lookup_word", "show_hint", "show_correction", "explain_grammar", "show_natural",
              "show_suggestions", "suggest_practice", "remember", "forget", "open_review", "open_video_region",
              "edit_today")
_ADDED_TO_NOTEBOOK = {"vi": "Mình đã thêm điểm ngữ pháp này vào Sổ tay để bạn luyện lại.",
                      "zh": "我把这个语法点加到你的笔记本里了，方便你再练习。",
                      "en": "I added this grammar point to your notebook so you can practise it again."}


def _spent_on_video(method):
    """M1 S7: model calls of a conversation are logged against its Library item (cost per session)."""
    @wraps(method)
    def scoped(self, session, *args, **kwargs):
        with usage_scope("companion", session.ticket.library_item_id):
            return method(self, session, *args, **kwargs)
    return scoped


def _run(coroutine):
    """The registry is shared with the voice channel (async); the text channel runs in a worker thread.

    Not `asyncio.run`: it joins the loop's worker threads before returning, so a request whose turn timed out would
    still wait for the abandoned model call. Closing the loop leaves such a thread to end on its own deadline."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        try:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()  # shuts its executor down without waiting for running threads


class TextChannel(ConversationSetup):
    plan = None  # TodayPlanEditor: edits today's tasks for the agent (set by the constructor)
    video_regions = None  # VideoRegionChecker: checks a video part the agent wants to open

    def __init__(self, *, model: ToolCallingModel | None, transcriber: SpeechTranscriber | None,
                 synthesizer: SpeechSynthesizer | None, tickets: CompanionTicketCodec | None,
                 sessions: SessionStore | None = None, consent=None, session_events=None,
                 pronunciation=None, learning_log=None, facts=None, memory=None, plan=None, video_regions=None,
                 context_builder: ContextBuilder | None = None, enabled: bool = True,
                 tracing: TurnTracing | None = None, **setup):
        super().__init__(**setup)
        self.model = model
        self.tracing = tracing if tracing is not None else NoopTracing()
        self.transcriber = transcriber
        self.synthesizer = synthesizer
        self.tickets = tickets  # signs the client's reference to a conversation
        # Where conversations live between turns; one process's memory unless the composition passes a shared store.
        self.sessions = sessions if sessions is not None else MemorySessionStore()
        self.consent, self.session_events = consent, session_events
        self.pronunciation = pronunciation
        self.learning_log = learning_log  # the learning log (activity module); None = not recording
        self.enabled = enabled  # channel configuration: "text" in AGENT_CHANNELS
        self.memory = memory  # AgentMemory: what the agent remembers across conversations
        self.plan, self.video_regions = plan, video_regions  # edit today's tasks; check a video region to open
        self.facts = facts
        if context_builder is not None:
            self.context_builder = context_builder  # shared across requests, so its short cache is used

    @property
    def facts(self):
        return self._facts

    @facts.setter
    def facts(self, value) -> None:
        self._facts = value
        self.context_builder = ContextBuilder(value, memory=self.memory)

    @property
    def tools(self) -> ToolRegistry:
        return ToolRegistry(facts=self.facts, word_lookup=self.word_lookup,
                            learning_log=self.learning_log, memory=self.memory,
                            plan=self.plan, video_regions=self.video_regions)

    # --- Start -----------------------------------------------------------------------------

    def start(self, user, entry, library_item_id: UUID | None, segment_id: UUID | None = None,
              topic_id: UUID | None = None, scenario_id: str | None = None,
              swap_roles: bool = False, *, text_only: bool = False) -> CompanionTurnView:
        if not text_only:
            self._require_consent(user.id)
        with traced("start", entry=entry.value) as trace, trace_turn(self.tracing, "start"):
            if (not self.enabled or self.model is None or self.tickets is None
                    or (not text_only and self.transcriber is None)):
                raise SpeakingPracticeError(*UNAVAILABLE)
            with trace.timed("context"):
                prepared = self.prepare(user, entry, library_item_id, segment_id, topic_id,
                                        scenario_id=scenario_id, swap_roles=swap_roles)
            session = self._with_context(TextSession(user=user, prepared=PreparedConversation(ticket=prepared.ticket),
                                                     id=prepared.ticket.session_id, text_only=text_only))
            trace.language = session.ticket.language_code
            opens = starts_open(entry, library_item_id=library_item_id, segment_id=segment_id, topic_id=topic_id,
                                scenario_id=scenario_id)
            if opens:
                session.mode = "open"
            output = self._model_turn(session, learner_said=None, event=None, trace=trace)
            self._require_session_consent(session)
            if session.ticket.scenario_id:
                self.tools.log_roleplay(session, session.ticket.scenario_id, session.ticket.swap_roles)
            view = self._respond(session, output, learner_said=None, trace=trace)
            if opens:
                view = view.model_copy(update={"choices": [CompanionChoiceView(**choice) for choice in opening_choices(
                    words=len(session.ticket.items) if prepared.focused else 0, context=session.context)]})
            _record(trace, view, session.ticket.language_code)
            return view

    # --- Finish ----------------------------------------------------------------------------

    def finish(self, user, token: str, *, day: date | None = None) -> CompanionFinishView:
        """The learner left: the conversation is closed, its state deleted and its follow-ups added to today's plan."""
        with traced("finish") as trace:
            reference = self._reference(user, token)
            session = self._load(user, reference)
            ticket = session.ticket
            trace.entry, trace.language, trace.turn = ticket.entry.value, ticket.language_code, session.turn
            self._claim(reference)
            self._forget(session)
            if not session.text_only and not self._has_consent(user.id):
                return CompanionFinishView()
            if ticket.library_item_id is not None:
                self.recheck_owner(user, ticket.library_item_id)
            return CompanionFinishView(follow_ups=self.follow_ups_after(user, ticket, session.history, day),
                                       **self._finish_feedback(session))

    # --- Turn ------------------------------------------------------------------------------

    def turn(self, user, token: str, audio: SpeechAudio | None = None, *, text: str | None = None,
             day: date | None = None, request: str | None = None, speak: bool = True) -> CompanionTurnView:
        """One learner turn, spoken (WAV) or typed (when the microphone is unavailable). `request` is a help button
        (hint, explain, natural, suggest): the learner asked for it explicitly, with or without words."""
        with traced("turn") as trace, trace_turn(self.tracing, "turn"):
            reference = self._reference(user, token)
            session = self._load(user, reference)
            self._require_session_consent(session)
            if session.text_only and audio is not None:
                raise SpeakingPracticeError("invalid_input", "companion_text_only",
                                            "This conversation accepts typed messages only.")
            ticket = session.ticket
            trace.entry, trace.language, trace.turn = ticket.entry.value, ticket.language_code, session.turn
            if not self.enabled or self.model is None or (audio is not None and self.transcriber is None):
                raise SpeakingPracticeError(*UNAVAILABLE)
            if session.turn >= MAX_TURNS:
                raise SpeakingPracticeError(*EXPIRED)
            if request is not None and request not in HELP_REQUESTS:
                raise SpeakingPracticeError("invalid_input", "companion_request_invalid", "Choose one of the help buttons.")
            if request is not None and session.help_requests >= MAX_HELP_REQUESTS:
                raise SpeakingPracticeError("conflict", "companion_help_limit", "That is enough help for this conversation.")
            said = (self._typed(text, allow_empty=request is not None) if audio is None
                    else self._transcribe(audio, ticket, trace))
            if ticket.library_item_id is not None:
                with trace.timed("context"):
                    self.recheck_owner(user, ticket.library_item_id)
            self._with_context(session)
            session.day = day
            session.learner_turn = [said]
            session.learner_spoke()
            # Hesitation is an event for the agent, which chooses the help (PRD 8.12 point 5); Scaffolding counts the
            # stalls in a row for the current question, as on the voice channel.
            event = None
            stalled = False
            if said:
                streak = session.scaffolding.learner_said(said, ticket.language_code)
                if streak is not None:
                    stalled = True
                    event = hesitation_event(stall_kind(said, ticket.language_code) or "stuck", streak)
            if request is not None:
                # An explicit press, like the voice channel's: the agent is told what the learner asked for, and for a
                # hint how much of one this question already showed.
                session.help_requests += 1
                if request == "hint":
                    session.scaffolding.tapped()
                event = learner_request(request, hint_seen=session.scaffolding.hint_step if request == "hint" else 0)
            if said:  # phase 6: how the learner is doing, told to the agent when it changed
                change = observe_pace(session, said, ticket.language_code, stalled=stalled, helped=request is not None)
                if change is not None:
                    event = "\n".join(part for part in (event, pace_note(change)) if part)
            examples_seen = len(session.examples)
            # The ticket is reserved before the model runs, so a second request carrying it (a double tap, a
            # retry while this one still runs) is refused before it costs a model call. A turn that fails gives it
            # back, so the learner can simply try again with the same ticket; a replayed ticket stays refused.
            self._claim(reference)
            try:
                output = self._model_turn(session, learner_said=said, trace=trace, event=event)
            except BaseException:
                self._release(reference)
                raise
            self._require_session_consent(session)
            if not session.text_only:
                # Commit after a successful model turn so a retry cannot repeat a memory write.
                _run(self.tools.commit_memory(session))
            if audio is not None and said and len(session.analysis_turns) < MAX_KEPT_LEARNER_TURNS:
                session.analysis_turns.append(LearnerTurn(text=clip_message(said), occurred_at=datetime.now(UTC),
                                                          examples_seen=examples_seen, truncated=len(said) > 300))
            if audio is not None:
                session.weak_words = self._score_turn(session, audio, said)
                session.speech_ms = min(600_000, session.speech_ms + voice_activity(audio).speech_ms)
            self._require_session_consent(session)
            view = self._respond(session, output, learner_said=said or None, trace=trace, took_turn=True, speak=speak)
            if view.finished:
                view.follow_ups = self.follow_ups_after(user, ticket, session.history, day)
            _record(trace, view, ticket.language_code)
            if not session.text_only:
                self._record_turn(session, view, typed=audio is None)
            return view

    def _typed(self, text: str | None, *, allow_empty: bool = False) -> str:
        said = " ".join((text or "").split())
        if allow_empty and not said:
            return ""
        if not said or len(said) > MAX_TYPED_CHARS:
            raise SpeakingPracticeError("invalid_input", "companion_text_invalid",
                                        "Type a short answer (up to 300 characters).")
        return said

    def _transcribe(self, audio: SpeechAudio, ticket: CompanionTicket, trace: CompanionTrace) -> str:
        if voice_activity(audio).speech_ms < 300:
            raise SpeakingPracticeError("invalid_input", "no_speech_detected", "No speech was detected.")
        try:
            with trace.timed("transcribe"):
                return self.transcriber.transcribe(audio, language_code=ticket.language_code).text
        except NoSpeechDetected as exc:
            raise SpeakingPracticeError("invalid_input", "no_speech_detected", "No speech was detected.") from exc
        except SpeechProviderFailure as exc:
            raise provider_failure_error(exc) from exc

    # --- The conversation on the server ------------------------------------------------------

    def load(self, user, token: str) -> TextSession:
        """The conversation this learner's ticket refers to, as stored (without the per-request learner context)."""
        return self._load(user, self._reference(user, token))

    def save(self, session: TextSession) -> tuple[str, datetime]:
        """Keep the conversation for its next turn under a new single-use ticket, which is returned."""
        token, reference = self.tickets.issue(session.id, session.user.id, started_at=session.ticket.started_at)
        session.token_id = reference.token_id
        state = dump_state(session)
        self._store(lambda: self.sessions.put(session.id, session.user.id, state,
                                              ttl_seconds=seconds_until(reference.expires_at)))
        return token, reference.expires_at

    def _reference(self, user, token: str) -> SessionToken:
        if self.tickets is None:
            raise SpeakingPracticeError(*UNAVAILABLE)
        try:
            reference = self.tickets.read(token)
        except InvalidCompanionTicket as exc:
            raise SpeakingPracticeError(*EXPIRED) from exc
        if reference.user_id != user.id:
            raise SpeakingPracticeError(*EXPIRED)
        return reference

    def _load(self, user, reference: SessionToken) -> TextSession:
        data = self._store(lambda: self.sessions.get(reference.conversation_id, user.id))
        if data is None:
            raise SpeakingPracticeError(*EXPIRED)  # expired, finished or never started
        try:
            session = load_state(data, user, reference.conversation_id)
        except (ValueError, KeyError, TypeError) as exc:
            raise SpeakingPracticeError(*EXPIRED) from exc  # a state this version cannot use ends the conversation
        if session.token_id != reference.token_id:
            raise SpeakingPracticeError(*EXPIRED)  # an older ticket of this conversation: its turn was taken
        return session

    def _release(self, reference: SessionToken) -> None:
        """A reserved ticket whose turn failed is usable again; a store failure leaves it spent (fail closed)."""
        try:
            self.sessions.release(reference.conversation_id, reference.user_id, reference.token_id)
        except SessionStoreUnavailable:
            logger.warning("companion ticket not released; the learner starts a new conversation")

    def _claim(self, reference: SessionToken) -> None:
        claimed = self._store(lambda: self.sessions.claim(
            reference.conversation_id, reference.user_id, reference.token_id,
            ttl_seconds=seconds_until(reference.expires_at)))
        if not claimed:
            raise SpeakingPracticeError(*EXPIRED)

    def _forget(self, conversation: TextSession | SessionToken) -> None:
        """The conversation is over: its state goes now. A failure leaves it to expire; its ticket is already spent."""
        if isinstance(conversation, TextSession):
            conversation_id, user_id = conversation.id, conversation.user.id
        else:
            conversation_id, user_id = conversation.conversation_id, conversation.user_id
        try:
            self.sessions.delete(conversation_id, user_id)
        except SessionStoreUnavailable:
            logger.warning("companion conversation not deleted; it expires with its ticket")

    @staticmethod
    def _store(action):
        try:
            return action()
        except SessionStoreUnavailable as exc:
            raise SpeakingPracticeError(*UNAVAILABLE) from exc

    def _with_context(self, session: TextSession) -> TextSession:
        """What the agent knows about the learner, read per request (ContextBuilder caches it briefly)."""
        ticket = session.ticket
        session.context = self.context_builder.build(session.user.id, ticket.language_code,
                                                     ticket.support_language_code, region_id=ticket.region_id,
                                                     include_memory=not session.text_only)
        if self.facts is not None:
            try:
                session.lesson_menu = self.facts.grammar_menu(session.user.id, ticket.language_code,
                                                              ticket.support_language_code)
            except Exception as exc:
                logger.warning("approved lessons unavailable error=%s", type(exc).__name__)
        return session

    def _has_consent(self, user_id: UUID) -> bool:
        try:
            return self.consent is not None and self.consent.has_consent(user_id) is True
        except Exception:
            return False

    def _require_consent(self, user_id: UUID) -> None:
        if not self._has_consent(user_id):
            raise SpeakingPracticeError("conflict", "voice_consent_required",
                                        "Allow voice processing in Profile to talk with the agent.")

    def _require_session_consent(self, session: TextSession) -> None:
        if session.text_only:
            return
        try:
            self._require_consent(session.user.id)
        except SpeakingPracticeError:
            self._forget(session)
            raise

    def _score_turn(self, session: TextSession, audio: SpeechAudio, text: str) -> list[str]:
        assessor, language = self.pronunciation, session.ticket.language_code
        if assessor is None or not assessor.supports(language) or session.turn >= MAX_SCORED_TURNS \
                or audio.duration_ms > MAX_TURN_AUDIO_MS or len(text) > MAX_TURN_TEXT_CHARS \
                or audio_quality_issues(audio):  # a quiet, clipped or very short recording is not scored
            return session.weak_words
        try:
            result = assessor.assess(audio, reference_text=text, language_code=language)
            return list(dict.fromkeys([*session.weak_words, *weak_words([result])]))[:MAX_WEAK_WORDS]
        except Exception as exc:
            logger.warning("fallback pronunciation unavailable error=%s", type(exc).__name__)
            return session.weak_words

    def _finish_feedback(self, session: TextSession) -> dict:
        ticket, user_id = session.ticket, session.user.id
        if session.text_only or not self._has_consent(user_id):
            return {}
        feedback = {"weak_words": list(session.weak_words)}
        observations = session.analysis_turns
        if not observations:
            return feedback
        log_activity(self.learning_log, user_id=user_id, language_code=ticket.language_code,
                     client_event_id=f"speaking_session:{session.id}", kind="speaking_session",
                     outcome="done", source_type="agent_session", source_id=str(session.id),
                     detail={"turns": len(observations), "seconds": session.speech_ms // 1000,
                             "channel": "text"})
        unavailable = {"session_id": str(session.id), "status": "unavailable"}
        if session.support_truncated or self.session_events is None or self.target_catalog is None:
            return {**feedback, "analysis": unavailable}
        try:
            saved = self.target_catalog.saved_items(user_id, language_code=ticket.language_code,
                                                    support_language_code=ticket.support_language_code)
            targets = saved_word_targets(saved, observations, ticket.language_code)
            if targets:
                data = SessionText(id=session.id, user_id=user_id,
                    language_code=ticket.language_code, library_item_id=ticket.library_item_id,
                    context_key=("video:" + str(ticket.library_item_id) if ticket.library_item_id
                                 else "home:" + ticket.topic[:100].casefold()), ended_at=datetime.now(UTC),
                    targets=[SelectedWord(concept_id=UUID(word.concept_id), text=word.text,
                                          meaning=word.meaning, forms=list(word.forms)) for word in targets],
                    turns=turns_with_server_support(observations, session.examples, targets, ticket.language_code),
                    examples=list(session.examples))
                feedback["analysis"] = self.session_events.submit(data)
        except Exception as exc:
            logger.warning("fallback analysis unavailable error=%s", type(exc).__name__)
            feedback["analysis"] = unavailable
        return feedback

    def _record_turn(self, session: TextSession, view: CompanionTurnView, *, typed: bool) -> None:
        """One learner turn in the learning log."""
        ticket = session.ticket
        log_activity(self.learning_log, user_id=ticket.user_id, language_code=ticket.language_code,
                     client_event_id=f"speaking_turn:{session.id}:{view.turn}", kind="speaking_turn",
                     outcome="done", source_type="agent_session", source_id=str(session.id),
                     detail={"channel": "text", "typed": typed, "hint_level": session.help_level,
                             "corrected": view.correction is not None})

    # --- The agent loop ----------------------------------------------------------------------

    @_spent_on_video
    def _model_turn(self, session: TextSession, *, learner_said: str | None, event: str | None,
                    trace: CompanionTrace) -> LoopResult:
        """The agent's turn: the conversation so far as messages (earlier tool calls and results included), then the
        learner's words (and a hesitation event or a help request). On success the turn joins the conversation."""
        ticket = session.ticket
        policy = level_policy(ticket.language_code, _declared_level(session))
        # The learner context and grammar points go before the turn checklist, which the model reads last.
        appendix = (roleplay_instruction(ticket.scenario_id, ticket.swap_roles)
                    + (session.context.render() if session.context else "")
                    + grammar_points_block(session.lesson_menu or None))
        system = build_agent_system_prompt(
            learning_language=ticket.language_code, support_language=ticket.support_language_code, policy=policy,
            topic=ticket.topic, mode=session.mode or "topic", items=list(ticket.items), region=bool(ticket.region_lines),
            excerpt=ticket.excerpt, practice_lines=self._practice_lines(session), appendix=appendix)
        if learner_said is None:  # the opening turn: a greeting needs no tools
            current = {"role": "user", "content": OPEN_START_CUE if session.mode == "open" else START_CUE}
            specs: list[ToolSpec] = []
        else:
            said = f"<learner_said>{data_text(learner_said)}</learner_said>" if learner_said else ""
            current = {"role": "user", "content": "\n".join(part for part in (said, event) if part)}
            specs = self._specs(text_only=session.text_only)
        loop = AgentLoop(self.model, self.tools)

        async def run_turn() -> LoopResult:
            deadline = loop.clock() + loop.max_seconds
            summary_timeout = min(2.0, loop.max_seconds / 3)
            try:
                session.messages = await asyncio.wait_for(asyncio.to_thread(
                    compact_history, self.model, session.messages, timeout=summary_timeout), summary_timeout)
            except TimeoutError:
                logger.warning("companion history summary timed out")
            messages = [*session.messages, current]
            result = await loop.run(session, system, messages, specs,
                                    validate=lambda text: self._language_note(session, text), deadline=deadline)
            session.messages = [*messages, *result.messages]  # the answer itself is added by _respond
            return result

        trace.model_attempts += 1
        try:
            with trace.timed("model"):
                result = _run(run_turn())
        except AgentLoopError as exc:
            trace.agent, trace.last_rejection = "fallback", exc.reason
            trace.model_attempts += exc.steps - 1
            raise SpeakingPracticeError("unavailable", "companion_turn_unavailable",
                                        "The companion could not answer. Please try again.") from exc
        trace.model_attempts += result.steps - 1
        trace.agent, trace.tool = ("tools" if result.tools else "respond"), (result.tools[-1] if result.tools else None)
        if result.rejections:
            trace.last_rejection = "LanguagePolicy"
        return result

    def _specs(self, *, text_only: bool = False) -> list[ToolSpec]:
        """The tools this conversation can use; a read needs its data source."""
        unavailable = set()
        if self.word_lookup is None:
            unavailable.add("lookup_word")
        if self.facts is None:
            unavailable |= {"get_recent_activity", "get_progress_summary", "get_due_cards", "get_study_requests",
                            "open_review"}
        if self.plan is None:
            unavailable.add("edit_today")
        if self.video_regions is None:
            unavailable.add("open_video_region")
        if text_only or self.memory is None:
            unavailable |= {"remember", "forget"}
        return [spec for spec in ToolRegistry.specs(text=True) if spec.name in TEXT_TOOLS
                and spec.name not in unavailable]

    @staticmethod
    def _language_note(session: TextSession, text: str) -> str | None:
        """The language policy (PRD 8.12 point 2), the core's: a slip is sent back to the agent."""
        return AgentCore.text_reply_note(session, text)

    def _practice_lines(self, session: TextSession) -> list[str]:
        """What the learner just practised in the study region, read from the learning log on every turn so practice
        done during the conversation (a suggested Dictation) is seen; a failed read means no lines."""
        ticket = session.ticket
        if self.facts is None or not ticket.region_id:
            return []
        try:
            rows = self.facts.region_activity(ticket.user_id, ticket.region_id, limit=20)
        except Exception as exc:
            logger.warning("companion practice log unavailable error=%s", type(exc).__name__)
            return []
        return practice_lines(rows, {line.segment_id: line.ref for line in ticket.region_lines})

    # --- Respond -------------------------------------------------------------------------------

    def _respond(self, session: TextSession, output: LoopResult, *, learner_said: str | None,
                 trace: CompanionTrace, took_turn: bool = False, speak: bool = True) -> CompanionTurnView:
        ticket = session.ticket
        items = {item.item_id: item for item in ticket.items}
        reply, reply_support, ended = split_reply(output.text)
        reply, reply_support = clean_transcript(reply).strip(), clean_transcript(reply_support).strip()
        shown = _shown(output.events)
        used = _used_items(ticket, learner_said)
        # The conversation keeps what the learner heard: the spoken reply (its support-language version is a gloss).
        session.messages.append({"role": "assistant", "content": " ".join(reply.split())})
        if learner_said is not None:
            session.history.append(CompanionMessage(role="learner", text=clip_message(learner_said)))
        session.history.append(CompanionMessage(role="companion", text=clip_message(reply)))
        session.history = session.history[-MAX_HISTORY_MESSAGES:]
        took_turn = took_turn or learner_said is not None  # a help button without words is a turn too
        session.turn += 1 if took_turn else 0
        correction = shown.get("correction")
        finished = session.turn >= MAX_TURNS or (ended and took_turn)
        session.used_item_ids = list(dict.fromkeys([*session.used_item_ids, *used]))
        # All support delivered to this client is conservatively treated as exposed: what the agent said and what
        # the tools showed (they note it on the session), and the words of a hint. The client cannot claim to have
        # hidden an answer in order to obtain independent-use credit.
        hint = shown.get("hint")
        for item in hint["items"] if hint else []:
            session.note_support(item["text"])
        study = shown.get("study_request")
        token, expires_at = (None, None)
        if finished:
            self._forget(session)
        else:
            token, expires_at = self.save(session)
        if session.text_only:
            audio, audio_status = None, "unavailable"
        elif speak:
            with trace.timed("synth"):
                audio, audio_status = self._speak(reply, ticket.language_code)
        else:  # the caller streams the reply's speech sentence by sentence (speak_parts)
            audio, audio_status = None, "streaming" if self._speakable(reply, ticket.language_code) else "unavailable"
        suggestion = _practice_suggestion(shown.get("practice_suggestion"))
        trace.region = bool(ticket.region_lines)
        if "suggest_practice" in output.tools:
            trace.suggestion = "shown" if suggestion is not None else "dropped"
        if study is not None:
            reply_support += " " + _ADDED_TO_NOTEBOOK.get(ticket.support_language_code, _ADDED_TO_NOTEBOOK["en"])
        return CompanionTurnView(
            session_ticket=token, expires_at=expires_at, turn=session.turn, max_turns=MAX_TURNS, finished=finished,
            language_code=ticket.language_code, support_language_code=ticket.support_language_code,
            entry=ticket.entry.value, library_item_id=ticket.library_item_id, topic=ticket.topic,
            learner_transcript=learner_said, reply=" ".join(reply.split()), reply_support=reply_support,
            hints=CompanionHintsView(
                question=_text(hint["question"]) if hint else None,
                items=[CompanionItemView(id=item["id"], text=item["text"], meaning=item["meaning"])
                       for item in (hint["items"] if hint else [])],
                frame=CompanionFrameView(frame=hint["frame"], reason=_text(hint["frame_reason"]) or hint["frame"])
                if hint and hint["frame"] else None,
                model_sentence=_text(hint["model_sentence"]) if hint else None,
            ),
            correction=CompanionCorrectionView(quote=correction["quote"], suggestion=correction["suggestion"],
                                               note=correction["note"]) if correction else None,
            used_items=[_item_view(items[item_id]) for item_id in used],
            next="close" if finished else "retry" if correction else "continue", audio=audio,
            audio_status=audio_status,
            looked_up=[_word_view(event["word"], entry) for event in output.events if event["type"] == "looked_up"
                       for entry in event["entries"]],
            practice_suggestion=suggestion,
            auto_hint_level=_hint_step(hint),
            study_request=CompanionStudyRequestView(kind=study["kind"], item=study["item"], title=study.get("title"))
            if study else None,
            grammar=CompanionGrammarView(
                title=shown["grammar"].get("title"), explanation=shown["grammar"]["explanation"],
                example=shown["grammar"].get("example"), rules=list(shown["grammar"].get("rules") or [])[:4],
                unverified=bool(shown["grammar"].get("unverified"))) if shown.get("grammar") else None,
            natural=[CompanionOptionView(**option) for option in shown.get("natural", [])],
            suggestions=[CompanionOptionView(**option) for option in shown.get("suggestions", [])],
            actions=_actions(output.events),
            **(self._finish_feedback(session) if finished else {}),
        )

    def _speakable(self, text: str, language: str) -> bool:
        # A reply in the support language (an A1-A2 explanation) is shown, not spoken by the learning-language voice.
        return (self.synthesizer is not None and self.synthesizer.supports(language)
                and bool(text.strip()) and reply_in_learning_script(text))

    def speak_parts(self, view: CompanionTurnView) -> Iterator[CompanionAudioView]:
        """The reply's speech one sentence at a time (harness plan, phase 4): the first is ready long before the whole
        reply would be. A part that cannot be synthesised ends the stream; the reply text is already shown."""
        if view.audio_status != "streaming":
            return
        for part in speech_parts(view.reply, view.language_code):
            audio, status = self._speak(part, view.language_code)
            if audio is None:
                return
            yield audio

    def _speak(self, text: str, language: str) -> tuple[CompanionAudioView | None, str]:
        if not self._speakable(text, language):
            return None, "unavailable"
        try:
            speech = self.synthesizer.synthesize(text, language_code=language)
        except SpeechSynthesisUnavailable:
            return None, "unavailable"
        return CompanionAudioView(mime_type=speech.mime_type,
                                  base64=base64.b64encode(speech.audio).decode("ascii")), "ready"



def _declared_level(session: TextSession) -> str | None:
    return session.context.declared_level if session.context else None


def _shown(events: list[dict]) -> dict:
    """What the agent put on the learner's screen this turn; the last of each kind wins."""
    shown: dict = {}
    for event in events:
        kind = event["type"]
        if kind in ("hint", "correction", "grammar", "study_request", "practice_suggestion"):
            shown[kind] = event
        elif kind in ("natural", "suggestions"):
            shown[kind] = event["items"]
    return shown


def _actions(events: list[dict]) -> list[CompanionActionView]:
    """The action cards of this turn, in order; the same event the voice channel sends, without its `type`."""
    cards = []
    for event in events:
        if event["type"] == "action":
            cards.append(CompanionActionView(**{key: value for key, value in event.items() if key != "type"}))
    return cards


def _hint_step(hint: dict | None) -> int | None:
    """The web opens a hint panel in steps: 1 question and words, 2 adds a frame, 3 adds a model sentence."""
    if hint is None:
        return None
    return 3 if hint["model_sentence"] else 2 if hint["frame"] else 1


def _practice_suggestion(event: dict | None) -> CompanionPracticeSuggestionView | None:
    if event is None:
        return None
    return CompanionPracticeSuggestionView(
        tool=event["tool"], segment_id=UUID(event["segment_id"]), start_ms=event["start_ms"], end_ms=event["end_ms"],
        reason=" ".join(event["reason"].split()))


def _used_items(ticket: CompanionTicket, learner_said: str | None) -> list[str]:
    if not learner_said:
        return []
    matchers = [HintMatcher(hint_id=item.item_id, forms=item.forms or (item.text,)) for item in ticket.items]
    return list(dict.fromkeys(used_hint_ids(learner_said, matchers, ticket.language_code)))


def _record(trace: CompanionTrace, view: CompanionTurnView, language: str) -> None:
    trace.language, trace.turn, trace.next = language, view.turn, view.next
    trace.reply_units = spoken_unit_count(view.reply, language)
    trace.has_correction = view.correction is not None
    trace.used_items = len(view.used_items)
    trace.audio = view.audio_status


def _word_view(word: str, entry: dict) -> CompanionWordView:
    return CompanionWordView(
        word=word, headword=entry["headword"],
        senses=[CompanionSenseView(text=sense["text"], part_of_speech=sense["part_of_speech"])
                for sense in entry["senses"]],
        source_name=entry["source_name"], source_license=entry["source_license"], source_url=entry["source_url"],
    )


def _item_view(item: CompanionItem) -> CompanionItemView:
    return CompanionItemView(id=item.item_id, text=item.text, meaning=item.meaning)


def _text(value: str | None) -> str | None:
    return " ".join(value.split()) if value and value.strip() else None


_SENTENCE_END = re.compile(r"(?<=[.!?。！？…])\s*")
MIN_PART_CHARS = 12  # a shorter sentence ("Yes!") is spoken together with the next one
MIN_PART_CHARS_ZH = 5  # Chinese packs a word into one or two characters


def speech_parts(text: str, language: str) -> list[str]:
    """The reply cut at sentence ends, short pieces joined to the next, so each part sounds natural on its own."""
    pieces = [piece.strip() for piece in _SENTENCE_END.split(" ".join(text.split())) if piece.strip()]
    parts: list[str] = []
    carry = ""
    chinese = language.startswith("zh")
    joiner, minimum = ("", MIN_PART_CHARS_ZH) if chinese else (" ", MIN_PART_CHARS)
    for piece in pieces:
        carry = f"{carry}{joiner}{piece}" if carry else piece
        if len(carry) >= minimum:
            parts.append(carry)
            carry = ""
    if carry:
        if parts:
            parts[-1] = f"{parts[-1]}{joiner}{carry}"
        else:
            parts.append(carry)
    return parts
