"""The agent's voice channel: learner <-> server <-> Gemini Live.

The learner's client opens a WebSocket to the backend and authenticates with its first message. The server
checks the channel configuration and the limits, builds the conversation (setup + ContextBuilder) exactly like
the text channel, opens the provider session and relays audio both ways. In voice the model itself is the agent
loop: Gemini Live calls the core's tools natively and every call goes through ToolRegistry. The rules are the text
loop's (PRD 8.12): the agent may help unasked; a help button is an explicit request sent to the agent as a short
message; Scaffolding reports hesitation (which stall, how many in a row) and the agent chooses the help; the
instruction states the same language policy. After each agent turn the transcript is checked: a grading claim ends
the session, a turn outside the language policy is sent back to the agent to say again (the session ends after
MAX_LANGUAGE_SLIPS in a row). With the learner's separate transcript consent (FR-3.11) the learner's turns are
kept as text after the session. No audio or transcript is logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.activity.contracts import log_activity
from app.modules.learning.application.agent.choices import opening_choices, starts_open
from app.modules.learning.application.agent.context import ContextBuilder
from app.modules.learning.application.agent.core import MAX_LANGUAGE_SLIPS, AgentCore  # noqa: F401 (re-exported)
from app.modules.learning.application.agent.realtime_port import (  # noqa: F401 (re-exported for the adapters)
    AudioOut,
    ClientChannel,
    Interrupted,
    RealtimeConnection,
    RealtimeEvent,
    RealtimeUnavailable,
    RealtimeVoice,
    Resumed,
    TokenVerifier,
    ToolCall,
    TranscriptPiece,
    TurnComplete,
)
from app.modules.learning.application.agent.voice_limits import (  # noqa: F401 (re-exported for the wiring)
    SESSION_SLOT_SLACK_S,
    GateStore,
    GateStoreUnavailable,
    MemoryGateStore,
    RealtimeGate,
    RealtimeGateUnavailable,
    SessionGrant,
)
from app.modules.learning.application.agent.client_resume import RUNNING, ReattachableChannel
from app.modules.learning.application.agent.memory_consolidation import KeptTurnText
from app.modules.learning.application.agent.pace import observe as observe_pace
from app.modules.learning.application.agent.pace import pace_note
from app.modules.learning.application.agent.realtime_resume import ResumableConnection
from app.modules.learning.application.agent.prompts import (
    CHOICE_CUES,
    VOICE_PROMPT_VERSION,
    build_voice_instruction,
    grammar_points_block,
    hesitation_event,
    learner_request,
    selected_word_hint,
)
from app.modules.learning.application.agent.scaffolding import stall_kind
from app.modules.learning.application.agent.session import AgentSession, Phase
from app.modules.learning.application.agent.setup import ConversationSetup
from app.modules.learning.application.agent.tools import TOOL_SPECS, ToolRegistry
from app.modules.learning.application.conversation_pronunciation import (
    MAX_SCORED_TURNS, MAX_TURN_AUDIO_MS, MAX_TURN_TEXT_CHARS, TurnAudioBuffer, weak_words,
)
from app.modules.learning.application.learned_items import LearnedItem
from app.modules.learning.application.session_events import LearnerTurn, SelectedWord, SessionEventsService, SessionText
from app.modules.learning.application.speaking_activity import record_pronunciation
from app.modules.learning.application.speaking_ports import NoSpeechDetected, SpeakingPracticeError, SpeechProviderFailure
from app.modules.learning.application.speaking_signals import pace_code, turn_length_code, turn_units
from app.modules.learning.application.spoken_words import saved_word_targets, turns_with_server_support
from app.modules.learning.domain.companion import CompanionEntry, CompanionMessage, clip_message
from app.modules.learning.domain.grammar_notes import grammar_notes
from app.modules.learning.domain.realtime import (
    INPUT_SAMPLE_RATE,
    RealtimeLimits,
    asks_to_explain,
    clean_transcript,
    hold_open_marker,
    valid_audio_frame,
)
from app.modules.learning.domain.roleplay import roleplay_instruction
from app.modules.learning.domain.speech_audio import SpeechAudio, audio_quality_issues, trim_to_speech, voice_activity
from app.platform.ai_budget import daily_budget, live_cost

logger = logging.getLogger(__name__)

AUTH_TIMEOUT_S = 10
MAX_HISTORY_MESSAGES = 80
MAX_KEPT_TURNS = 40
CONSENT_RECHECK_S = 5.0  # a revoked voice consent stops a running conversation within this time
SCAFFOLD_TICK_S = 0.25  # how often the silence after a question is checked
CONTEXT_TIMEOUT_S = 4.0
MIN_FRAME_SPEECH_MS = 60  # a frame with this much voiced audio means the learner is talking
MAX_HELP_REQUESTS = 20  # help buttons and "why?" questions per session
MAX_SPOKEN_MS = 3_600_000  # an hour of the learner's own speech is more than any session allows
_REQUEST_ACTIONS = {"help": "hint", "explain": "explain", "natural": "natural", "suggest": "suggest"}


# --- Messages from the learner's client ------------------------------------------------------

class _Auth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["auth"]
    token: str


class _Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["start"]
    entry: CompanionEntry
    library_item_id: UUID | None = None
    day: date | None = None
    # Free conversation only: the notebook to practise words from. The agent picks the words.
    topic_id: UUID | None = None
    # The transcript part the learner is watching; the server re-checks that it belongs to their video.
    segment_id: UUID | None = None
    scenario_id: str | None = Field(default=None, min_length=1, max_length=40)
    swap_roles: bool = False


class _Resume(BaseModel):
    """A new socket for a session whose socket dropped: the events after `last_seq` (counted by the client)."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["resume"]
    session_id: UUID
    last_seq: int = Field(ge=0)


@dataclass
class KeptTurn:
    """One learner turn as kept with the transcript consent (FR-3.11): text and scores, never audio."""
    turn_index: int
    learner_text: str
    agent_text: str
    assistance_level: int
    occurred_at: datetime
    grammar_errors: list[dict] = field(default_factory=list)
    pronunciation: object | None = None  # the turn's PronunciationResult, when Azure scored it


@dataclass
class VoiceSession(AgentSession):
    """The core session plus what only a live audio conversation has."""

    turn_assistance: list[UUID] = field(default_factory=list)
    turn_examples_seen: int = 0
    turn_occurred_at: datetime | None = None
    turn_support_truncated: bool = False
    analysis: dict | None = None
    turn_sizes: list[int] = field(default_factory=list)
    speech_ms: int = 0
    speech_units: int = 0
    # How long the learner spoke in the whole conversation (voice activity of every turn), for "speaking time".
    spoken_ms: int = 0
    recurring_errors: list[str] = field(default_factory=list)
    # Pronunciation feedback: this turn's audio lives in memory only, until it is scored and dropped.
    score_speech: bool = False
    audio: TurnAudioBuffer = field(default_factory=TurnAudioBuffer)
    turn_audio: tuple[bytes, bool] | None = None
    pron_tasks: list = field(default_factory=list)
    pron_results: list = field(default_factory=list)
    output_rate: int | None = None
    audio_in_s: float = 0.0
    audio_out_s: float = 0.0
    # FR-3.11: the learner's turns as text, collected only when both consents were granted at the start and
    # stored after the session only if they still are. Memory only until then; never logged.
    keep_transcripts: bool = False
    kept_turns: list[KeptTurn] = field(default_factory=list)
    turn_prompt: str = ""
    turn_help_level: int = 0
    pending_corrections: list[dict] = field(default_factory=list)
    # FR-3.11 memory: the learner's own earlier turns read back for this conversation (both consents granted).
    past_turns: list[dict] = field(default_factory=list)
    # A provider marker ("<no speech>") can arrive in pieces: the unfinished start of one, per speaker.
    marker_carry: dict = field(default_factory=dict)
    # When the learner will have heard the agent's turn: the clock when its first audio frame went to the client,
    # and the seconds of audio sent in the turn so far (the provider can generate faster than real time).
    turn_audio_started: float | None = None
    turn_audio_s: float = 0.0
    core: AgentCore | None = None  # the tools and reply rules of this conversation, as on the text channel
    resumes: int = 0  # new provider connections this conversation went on with
    help_seen: int = 0  # help requests already counted for the pace (one learner turn at a time)
    pace_pending: str | None = None  # a delivery note for the agent, sent once its turn is complete
    reattaches: int = 0  # new learner sockets this conversation went on with


@dataclass(frozen=True)
class VoicePolicy:
    """Channel configuration: voice is on when AGENT_CHANNELS lists it, for the listed learners only."""
    enabled: bool
    allowed_user_ids: frozenset[UUID]
    limits: RealtimeLimits


def _client_action(data) -> str | None:
    try:
        message = json.loads(data or "")
    except ValueError:
        return None
    return message.get("type") if isinstance(message, dict) and isinstance(message.get("type"), str) else None


def _client_field(data, name: str) -> str | None:
    try:
        message = json.loads(data or "")
    except ValueError:
        return None
    value = message.get(name) if isinstance(message, dict) else None
    return value if isinstance(value, str) else None


class VoiceChannel:
    def __init__(self, *, setup: ConversationSetup, voice: RealtimeVoice | None, gate: RealtimeGate,
                 verifier: TokenVerifier, policy: VoicePolicy,
                 session_events: SessionEventsService | None = None, pronunciation=None, signals=None,
                 consent=None, transcripts=None, tasks=None, scores=None, consolidator=None,
                 learning_log=None, facts=None, memory=None, plan=None, video_regions=None,
                 monotonic: Callable[[], float] = time.monotonic):
        self.setup = setup
        self.voice = voice
        self.gate = gate
        self.verifier = verifier
        self.policy = policy
        self.session_events = session_events
        self.pronunciation = pronunciation
        self.signals = signals
        self.consent = consent
        self.transcripts = transcripts
        self.consolidator = consolidator  # MemoryConsolidator: the agent's notes from the kept turns, after the session
        self.tasks = tasks  # (user, day) -> today's plan items as JSON-ready dicts; None when not wired
        self.scores = scores
        self.learning_log = learning_log  # the learning log (activity module); None = not recording
        self.memory = memory  # AgentMemory: what the agent remembers across conversations
        self.plan, self.video_regions = plan, video_regions  # edit today's tasks; check a video region to open
        self.monotonic = monotonic
        self.live = RUNNING  # this process's running sessions, by id (reattach), shared by every channel object
        self.facts = facts

    @property
    def facts(self):
        return self._facts

    @facts.setter
    def facts(self, value) -> None:
        self._facts = value
        self.context_builder = ContextBuilder(value, memory=self.memory)

    @property
    def tools(self) -> ToolRegistry:
        return ToolRegistry(facts=self.facts, word_lookup=self.setup.word_lookup,
                            tasks=self.tasks, learning_log=self.learning_log, memory=self.memory,
                            plan=self.plan, video_regions=self.video_regions, transcripts=self.transcripts)

    async def run(self, channel: ClientChannel) -> None:
        user = await self._authenticate(channel)
        if user is None:
            return
        if not self.policy.enabled or self.voice is None or user.id not in self.policy.allowed_user_ids:
            await self._refuse(channel, 4403, "realtime_not_available",
                               "Realtime conversation is not available for this account.")
            return
        start = await self._start_message(channel)
        if start is None:
            return
        if isinstance(start, _Resume):
            await self._reattach(channel, user, start)
            return
        if not await self._has_consent(user):
            await self._refuse(channel, 4403, "voice_consent_required",
                               "Allow voice processing in Profile to talk with the agent.")
            return
        spending = daily_budget()
        if not await asyncio.to_thread(spending.allows):
            await self._refuse(channel, 4429, "realtime_limit",
                               "You have reached the realtime limit for now. Try the regular conversation.")
            return
        try:
            budget = await asyncio.to_thread(self.gate.acquire, user.id)
        except RealtimeGateUnavailable:
            await self._refuse(channel, 1011, "realtime_unavailable",
                               "Realtime conversation is unavailable right now. Try the regular conversation.")
            return
        if budget is None:
            await self._refuse(channel, 4429, "realtime_limit",
                               "You have reached the realtime limit for now. Try the regular conversation.")
            return
        session = None
        reservation = None
        try:
            reservation = await asyncio.to_thread(spending.reserve, live_cost(budget, budget))
            if reservation is None:
                await self._refuse(channel, 4429, "realtime_limit",
                                   "You have reached the realtime limit for now. Try the regular conversation.")
                return
            try:
                prepared = await asyncio.to_thread(self.setup.prepare, user, start.entry, start.library_item_id,
                    start.segment_id, start.topic_id,
                    **({"scenario_id": start.scenario_id, "swap_roles": start.swap_roles} if start.scenario_id else {}))
            except SpeakingPracticeError as exc:
                await self._refuse(channel, 4400, exc.code, str(exc))
                return
            session = VoiceSession(user=user, prepared=prepared, day=start.day, started=time.monotonic(),
                                   transient=prepared.focused,
                                   mode="open" if starts_open(
                                       start.entry, library_item_id=start.library_item_id, segment_id=start.segment_id,
                                       topic_id=start.topic_id, scenario_id=start.scenario_id) else None,
                                   score_speech=bool(self.pronunciation is not None
                                                     and self.pronunciation.supports(prepared.ticket.language_code)))
            session.scaffolding.clock = self.monotonic
            if prepared.ticket.scenario_id:
                await asyncio.to_thread(self.tools.log_roleplay, session, prepared.ticket.scenario_id,
                                        prepared.ticket.swap_roles)
            session.recurring_errors = await self._recurring_errors(user, prepared.ticket.language_code)
            session.keep_transcripts = await self._may_keep_transcripts(user)
            if session.keep_transcripts:
                session.past_turns = await self._past_turns(user, prepared.ticket.language_code)
            await self._load_context(session)
            # The learner's socket may drop and come back within a few seconds (ReattachableChannel).
            client = ReattachableChannel(channel, user_id=user.id)
            self.live[session.id] = client
            try:
                await self._converse(client, session, budget)
            finally:
                self.live.pop(session.id, None)
                client.finished.set()
        finally:
            await asyncio.to_thread(self.gate.release, user.id,
                                    time.monotonic() - session.started if session else 0.0, budget)
            if reservation is not None:
                cost = live_cost(session.audio_in_s, session.audio_out_s) if session else 0.0
                await asyncio.to_thread(spending.charge, cost, reservation=reservation)

    # --- Steps -------------------------------------------------------------------------------

    async def _authenticate(self, channel: ClientChannel):
        try:
            kind, data = await asyncio.wait_for(channel.receive(), AUTH_TIMEOUT_S)
            auth = _Auth.model_validate_json(data) if kind == "text" else None
        except (asyncio.TimeoutError, ValidationError, ValueError):
            auth = None
        if auth is None or auth.token.count(".") != 2:
            await self._refuse(channel, 4401, "authentication_required", "Sign in again.")
            return None
        try:
            return await asyncio.to_thread(self.verifier.verify, auth.token.strip())
        except Exception:
            await self._refuse(channel, 4401, "authentication_required", "Sign in again.")
            return None

    async def _start_message(self, channel: ClientChannel) -> _Start | _Resume | None:
        try:
            kind, data = await asyncio.wait_for(channel.receive(), AUTH_TIMEOUT_S)
            if kind == "text" and _client_action(data) == "resume":
                return _Resume.model_validate_json(data)
            return _Start.model_validate_json(data) if kind == "text" else None
        except (asyncio.TimeoutError, ValidationError, ValueError):
            await self._refuse(channel, 4400, "realtime_start_invalid", "Choose where to start the conversation.")
            return None

    async def _reattach(self, channel: ClientChannel, user, resume: _Resume) -> None:
        """The same learner's new socket takes over their running session; it stays open until the session ends."""
        client = self.live.get(resume.session_id)
        if client is None or client.user_id != user.id or not await client.attach(channel, resume.last_seq):
            await self._refuse(channel, 4404, "realtime_session_gone", "This conversation has ended.")
            return
        await client.finished.wait()

    async def _load_context(self, session: VoiceSession) -> None:
        """What the agent knows about the learner (ContextBuilder) and the approved grammar points it may name."""
        ticket = session.ticket
        try:
            session.context = await asyncio.wait_for(asyncio.to_thread(
                self.context_builder.build, session.user.id, ticket.language_code, ticket.support_language_code,
                region_id=ticket.region_id), CONTEXT_TIMEOUT_S)
        except Exception as exc:
            logger.warning("agent context unavailable error=%s", type(exc).__name__)
        if self.facts is None:
            return
        try:
            session.lesson_menu = await asyncio.wait_for(asyncio.to_thread(
                self.facts.grammar_menu, session.user.id, ticket.language_code, ticket.support_language_code),
                CONTEXT_TIMEOUT_S) or False
        except Exception as exc:
            logger.warning("approved lessons unavailable error=%s", type(exc).__name__)
            session.lesson_menu = False

    async def _converse(self, channel: ClientChannel, session: VoiceSession, budget: int) -> None:
        ticket = session.ticket
        if session.mode == "open":
            session.choices = opening_choices(words=len(ticket.items) if session.transient else 0,
                                              context=session.context)
        instruction = build_voice_instruction(
            mode=session.mode, learning_language=ticket.language_code, topic=ticket.topic, items=list(ticket.items),
            excerpt=ticket.excerpt, support_language=ticket.support_language_code,
            recurring_errors=session.recurring_errors, past_turns=session.past_turns,
            offer_tasks=self.tasks is not None and ticket.entry == CompanionEntry.HOME and not session.transient
            and session.mode != "open",
            learner_context=session.context.render() if session.context else "",
            grammar_points=grammar_points_block(session.lesson_menu or None),
            declared_level=session.context.declared_level if session.context else None)
        instruction += roleplay_instruction(ticket.scenario_id, ticket.swap_roles)
        open_args = dict(language_code=ticket.language_code, instruction=instruction,
                         silence_ms=self.policy.limits.end_of_turn_silence_ms)
        try:
            # One conversation across provider connections: resumed on goAway or a dropped connection.
            connection = ResumableConnection(self.voice, await self.voice.open(**open_args), open_args=open_args)
        except Exception as exc:
            logger.warning("realtime provider unavailable error=%s", type(exc).__name__)
            await self._refuse(channel, 1011, "realtime_unavailable",
                               "Realtime conversation is unavailable right now. Try the regular conversation.")
            session.end_reason = "provider_unavailable"
            self._trace(session)
            return
        await channel.send_json({"type": "ready", "session_id": str(session.id), "max_seconds": budget,
                                 "input_sample_rate": INPUT_SAMPLE_RATE,
                                 "language_code": ticket.language_code, "topic": ticket.topic, "mode": session.mode})
        if session.choices:
            await channel.send_json({"type": "choices", "items": list(session.choices)})
        tasks = [asyncio.create_task(self._from_learner(channel, connection, session)),
                 asyncio.create_task(self._from_provider(channel, connection, session)),
                 asyncio.create_task(self._watch_consent(session)),
                 asyncio.create_task(self._scaffold(connection, session))]
        try:
            done, _ = await asyncio.wait(set(tasks), timeout=budget, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                session.end_reason = session.end_reason or "time_limit"
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await connection.close()
        session.wrap_up()
        await self._flush_turn(session)
        follow_ups = await self._finish(session)
        await self._safe(channel.send_json({"type": "ended", "reason": session.end_reason or "ended",
                                            **({"summary": self._summary(session)} if session.learner_turns else {}),
                                            "follow_ups": [item.model_dump(mode="json") for item in follow_ups],
                                            **({"analysis": session.analysis} if session.analysis else {})}))
        await self._safe(channel.close(1000))
        session.end()
        session.reattaches = getattr(channel, "reattaches", 0)
        self._trace(session)

    async def _watch_consent(self, session: VoiceSession) -> None:
        """Audio stops soon after the learner revokes; a consent that cannot be read counts as not given."""
        while True:
            await asyncio.sleep(CONSENT_RECHECK_S)
            if not await self._has_consent(session.user):
                session.score_speech = False  # the turn in progress must not go to Azure
                session.end_reason = session.end_reason or "consent_revoked"
                return

    async def _scaffold(self, connection: RealtimeConnection, session: VoiceSession) -> None:
        """Five seconds of silence after the learner heard a question is reported to the agent, which chooses."""
        while True:
            await asyncio.sleep(SCAFFOLD_TICK_S)
            if session.mode == "open" and session.phase == Phase.GREETING:
                session.scaffolding.pause()  # nothing was chosen yet: there is no answer to hint at
                continue
            streak = session.scaffolding.tick()
            if streak is not None:
                await self._report_stall(connection, session, "silence", streak)

    async def _report_stall(self, connection: RealtimeConnection, session: VoiceSession, kind: str,
                            streak: int) -> None:
        """PRD 8.12 point 5: the server only says what happened; the agent chooses the help."""
        message = hesitation_event(kind, streak)
        if session.transient:
            message += selected_word_hint([item.text for item in session.ticket.items])
        session.auto_hint_pending = True
        await connection.send_text(message)

    async def _learner_asked(self, connection: RealtimeConnection, session: VoiceSession, kind: str) -> None:
        """A help button (or "why?" said aloud): an explicit request, delivered to the agent as a short message."""
        session.help_requests += 1
        if kind == "hint":
            session.scaffolding.tapped()
            session.auto_hint_pending = False
            message = learner_request("hint", hint_seen=session.scaffolding.hint_step)
            if session.transient:
                message += selected_word_hint([item.text for item in session.ticket.items])
        elif kind == "explain":
            message = learner_request("explain") + (session.lesson_menu.cue() if session.lesson_menu else "")
        else:
            message = learner_request(kind)
        await connection.send_text(message)

    async def _from_learner(self, channel: ClientChannel, connection: RealtimeConnection, session: VoiceSession) -> None:
        while True:
            kind, data = await channel.receive()
            if kind == "closed":
                session.end_reason = session.end_reason or "learner_left"
                return
            if kind == "text":
                action = _client_action(data)
                if action == "end":
                    session.end_reason = session.end_reason or "learner_ended"
                    return
                if action in _REQUEST_ACTIONS and session.help_requests < MAX_HELP_REQUESTS:
                    await self._learner_asked(connection, session, _REQUEST_ACTIONS[action])
                if action == "choose":
                    cue = self._choice_cue(session, _client_field(data, "id"))
                    if cue:
                        session.learner_spoke()
                        await connection.send_text(cue)
                continue  # other control text is ignored
            if not valid_audio_frame(data):
                session.end_reason = "invalid_audio"
                return
            session.audio_in_s += len(data) / 2 / INPUT_SAMPLE_RATE
            session.audio.add(data)  # memory only, bounded; dropped after each turn
            if session.scaffolding.waiting_since is not None and _voiced(data):
                session.scaffolding.pause()  # the learner started to answer
            await connection.send_audio(data)

    async def _from_provider(self, channel: ClientChannel, connection: RealtimeConnection, session: VoiceSession) -> None:
        language = session.ticket.language_code
        try:
            async for event in connection.events():
                if isinstance(event, AudioOut):
                    if event.sample_rate != session.output_rate:
                        # Binary frames carry no header: say the format before the first one, and on change.
                        session.output_rate = event.sample_rate
                        await channel.send_json({"type": "audio_format", "sample_rate": event.sample_rate,
                                                 "encoding": "pcm_s16le", "channels": 1})
                    seconds = len(event.pcm) / 2 / event.sample_rate
                    session.audio_out_s += seconds
                    if session.turn_audio_started is None:
                        session.turn_audio_started = self.monotonic()
                    session.turn_audio_s += seconds
                    await channel.send_bytes(event.pcm)
                elif isinstance(event, TranscriptPiece):
                    await self._transcript(channel, connection, session, event, language)
                elif isinstance(event, ToolCall):
                    # In order: Live waits for the function's response before it goes on, and a display or action
                    # call belongs to the learner turn being spoken.
                    await self._tool_call(channel, connection, session, event)
                elif isinstance(event, Resumed):
                    session.resumes += 1
                    await channel.send_json({"type": "resumed"})
                elif isinstance(event, Interrupted):
                    if session.tracks:
                        await self._flush_turn(session, channel)
                    session.turn_audio_started, session.turn_audio_s = None, 0.0  # the client stops playing
                    await channel.send_json({"type": "interrupted"})
                elif isinstance(event, TurnComplete):
                    reply = "".join(session.companion_turn)
                    stalled = await self._flush_turn(session, channel)
                    await channel.send_json({"type": "turn_complete"})
                    core = self._core(session)
                    core.begin_turn(session)
                    verdict = core.voice_reply(session, reply)
                    if verdict.end:
                        session.breach, session.end_reason = verdict.breach, "policy"
                        return
                    if verdict.note:
                        await connection.send_text(verdict.note)
                    if session.pace_pending:
                        # Context for the next replies, not a cue: the model does not answer it by itself.
                        note, session.pace_pending = session.pace_pending, None
                        await connection.send_context(note)
                    session.scaffolding.agent_turn(reply, self._playback_ends(session))
                    if stalled is not None:
                        await self._report_stall(connection, session, *stalled)
        except RealtimeUnavailable as exc:
            logger.warning("realtime provider closed error=%s", type(exc).__name__)
        session.end_reason = session.end_reason or "provider_closed"

    def _playback_ends(self, session: VoiceSession) -> float | None:
        """When the learner will have heard this turn: first frame sent + the audio's length (no client change)."""
        started, seconds = session.turn_audio_started, session.turn_audio_s
        session.turn_audio_started, session.turn_audio_s = None, 0.0
        return started + seconds if started is not None else None

    def _core(self, session: VoiceSession) -> AgentCore:
        """The conversation's core: what Gemini Live was declared (TOOL_SPECS), with the text channel's limits."""
        if session.core is None:
            session.core = AgentCore(self.tools, TOOL_SPECS)
        return session.core

    async def _transcript(self, channel: ClientChannel, connection: RealtimeConnection, session: VoiceSession,
                          event: TranscriptPiece, language: str) -> None:
        joined = session.marker_carry.pop(event.role, "") + event.text
        usable, held = hold_open_marker(joined)
        if held:
            session.marker_carry[event.role] = held
        text = clean_transcript(usable)
        if not text.strip() and (held or text != usable or usable != event.text):
            return  # a provider marker or silence is not speech: no line, no turn
        session.scaffolding.pause()
        if event.role == "learner" and not session.learner_turn:
            # Barge-in can arrive before the agent's turn-complete event.
            session.note_support("".join(session.companion_turn))
            session.turn_occurred_at = datetime.now(UTC)
            if session.keep_transcripts:
                # The agent turn this learner turn answers, and the help reached before it.
                session.turn_prompt = " ".join("".join(session.companion_turn).split()) or next(
                    (message.text for message in reversed(session.history) if message.role == "companion"), "")
                session.turn_help_level = session.help_level
            session.explain_asked = False
            session.turn_assistance = list(session.assisted_ids)
            session.turn_examples_seen = len(session.examples)
            session.turn_support_truncated = session.support_truncated
            session.learner_spoke()
        if event.role == "companion" and session.learner_turn and session.turn_audio is None:
            session.turn_audio = session.audio.take()  # the learner has finished: keep only their part
        (session.learner_turn if event.role == "learner" else session.companion_turn).append(text)
        if event.role == "learner" and not session.explain_asked and session.help_requests < MAX_HELP_REQUESTS \
                and asks_to_explain("".join(session.learner_turn), language):
            # They asked why in words: the same as pressing Explain, once per turn.
            session.explain_asked = True
            await self._learner_asked(connection, session, "explain")
        if text:
            await channel.send_json({"type": "transcript", "role": event.role, "text": text})

    @staticmethod
    def _choice_cue(session: VoiceSession, choice: str | None) -> str | None:
        """The cue for a tapped opening choice; only a choice that was offered counts, and only once."""
        if choice is None or choice not in {offered["id"] for offered in session.choices}:
            return None
        if choice == "words":
            session.mode = "topic"
        return CHOICE_CUES[choice]

    async def _tool_call(self, channel: ClientChannel, connection: RealtimeConnection, session: VoiceSession,
                         call: ToolCall) -> None:
        """Every call gets a response; only validated content reaches the learner."""
        result = await self._core(session).call(session, call.name, call.args)
        for event in result.events:
            await channel.send_json(event)
        if result.correction is not None and session.keep_transcripts:
            self._keep_correction(session, result.correction)
        await connection.send_tool_response(call.id, call.name, result.response)

    @staticmethod
    def _summary(session: VoiceSession) -> dict:
        """Counts and word names only: no speech, no scores, nothing stored."""
        return {"spoken_turns": session.learner_turns, "corrections": session.corrections,
                "hints": session.hints, "suggestions": session.suggestions,
                "words_to_reuse": session.reuse_words[:6],
                **({"error_types": list(session.error_codes),
                    "grammar_notes": grammar_notes(session.error_codes, session.ticket.language_code,
                                                   session.ticket.support_language_code)}
                   if session.error_codes else {}),
                **({"weak_words": weak} if (weak := weak_words(session.pron_results)) else {}),
                **({"study_requests": session.study_requests} if session.study_requests else {})}

    async def _flush_turn(self, session: VoiceSession, channel: ClientChannel | None = None) -> tuple[str, int] | None:
        """Close the turn; returns (kind, number in a row) when the learner's utterance was a stall (fillers,
        "I can't say it") still to be reported to the agent."""
        said = " ".join("".join(session.learner_turn).split())
        reply = " ".join("".join(session.companion_turn).split())
        audio = session.turn_audio if session.turn_audio is not None else session.audio.take()
        session.turn_audio = None
        stalled = None
        if said:
            streak = session.scaffolding.learner_said(said, session.ticket.language_code)
            if streak is not None:
                stalled = (stall_kind(said, session.ticket.language_code) or "stuck", streak)
            kept = self._keep_turn(session, said)
            self._observe_turn(session, audio, said, kept, channel)
            change = observe_pace(session, said, session.ticket.language_code, stalled=streak is not None,
                                  helped=session.help_requests > session.help_seen)
            session.help_seen = session.help_requests
            if change is not None:
                session.pace_pending = pace_note(change)
            session.learner_turns += 1
            if session.tracks and len(session.analysis_turns) < 40:
                session.analysis_turns.append(LearnerTurn(
                    text=clip_message(said), assisted_ids=session.turn_assistance,
                    occurred_at=session.turn_occurred_at,
                    examples_seen=session.turn_examples_seen,
                    truncated=len(said) > 300 or session.turn_support_truncated,
                ))
            session.history.append(CompanionMessage(role="learner", text=clip_message(said)))
            if session.consented:
                await asyncio.to_thread(
                    log_activity, self.learning_log, user_id=session.user.id,
                    language_code=session.ticket.language_code,
                    client_event_id=f"speaking_turn:{session.id}:{session.learner_turns}",
                    kind="speaking_turn", outcome="done", source_type="agent_session",
                    source_id=str(session.id), detail={"channel": "voice", "hint_level": session.help_level,
                                                       "stalled": stalled is not None})
        if reply:
            session.note_support(reply)
            session.history.append(CompanionMessage(role="companion", text=clip_message(reply)))
            session.turns += 1
        session.history = session.history[-MAX_HISTORY_MESSAGES:]
        session.learner_turn, session.companion_turn = [], []
        session.marker_carry.clear()
        return stalled

    @staticmethod
    def _keep_turn(session: VoiceSession, said: str) -> KeptTurn | None:
        if not session.keep_transcripts or len(session.kept_turns) >= MAX_KEPT_TURNS:
            session.pending_corrections = []
            return None
        kept = KeptTurn(turn_index=len(session.kept_turns), learner_text=said, agent_text=session.turn_prompt,
                        assistance_level=session.turn_help_level,
                        occurred_at=session.turn_occurred_at or datetime.now(UTC),
                        grammar_errors=session.pending_corrections[:10])
        session.kept_turns.append(kept)
        session.pending_corrections, session.turn_prompt, session.turn_help_level = [], "", 0
        return kept

    @staticmethod
    def _keep_correction(session: VoiceSession, correction: dict) -> None:
        """A correction belongs to the learner turn it quotes: the one still being spoken, or the last one."""
        if session.learner_turn:
            session.pending_corrections.append(correction)
        elif session.kept_turns and len(session.kept_turns[-1].grammar_errors) < 10:
            session.kept_turns[-1].grammar_errors.append(correction)

    def _observe_turn(self, session: VoiceSession, audio: tuple[bytes, bool], said: str,
                      kept: KeptTurn | None = None, channel: ClientChannel | None = None) -> None:
        """What one turn tells about how the learner speaks (counts only), and, when Azure can score the
        language, start scoring it in the background; the conversation never waits for it."""
        pcm, truncated = audio
        language = session.ticket.language_code
        session.spoken_ms = min(MAX_SPOKEN_MS, session.spoken_ms + voice_activity(SpeechAudio(pcm)).speech_ms)
        units = turn_units(said, language)
        session.turn_sizes.append(units)
        clip = trim_to_speech(SpeechAudio(pcm))
        # A long turn, or one whose start was cut off, would not match the words: do not judge it.
        if clip is None or clip.duration_ms > MAX_TURN_AUDIO_MS or (truncated and len(clip.pcm) >= len(pcm) - 6400):
            return
        session.speech_ms += clip.duration_ms
        session.speech_units += units
        if audio_quality_issues(clip):
            return  # too quiet, clipped or too short: its score would describe the microphone, not the learner
        if session.score_speech and len(session.pron_tasks) < MAX_SCORED_TURNS and len(said) <= MAX_TURN_TEXT_CHARS:
            session.pron_tasks.append(asyncio.get_running_loop().create_task(
                self._assess(session, clip, said, language, kept, channel, session.learner_turns + 1)))

    async def _assess(self, session: VoiceSession, clip: SpeechAudio, said: str, language: str,
                      kept: KeptTurn | None = None, channel: ClientChannel | None = None, turn: int = 0) -> None:
        try:
            result = await asyncio.to_thread(self.pronunciation.assess, clip, reference_text=said,
                                             language_code=language)
        except (NoSpeechDetected, SpeechProviderFailure):
            return
        except Exception as exc:
            logger.warning("conversation pronunciation unavailable error=%s", type(exc).__name__)
            return
        session.pron_results.append(result)
        if kept is not None:
            kept.pronunciation = result
        if channel is not None and session.score_speech:
            # This turn's score for the learner's screen: one overall number and the words that sounded wrong.
            await self._safe(channel.send_json({
                "type": "pronunciation", "turn": turn, "overall": round(result.scores.pronunciation),
                "weak_words": weak_words([result])[:3]}))

    async def _has_consent(self, user) -> bool:
        if self.consent is None:
            return False
        try:
            return bool(await asyncio.to_thread(self.consent.has_consent, user.id))
        except Exception as exc:
            logger.warning("voice consent unavailable error=%s", type(exc).__name__)
            return False  # no answer is not a yes

    async def _may_keep_transcripts(self, user) -> bool:
        if self.transcripts is None:
            return False
        try:
            return bool(await asyncio.to_thread(self.transcripts.may_keep, user.id))
        except Exception as exc:
            logger.warning("transcript consent unavailable error=%s", type(exc).__name__)
            return False  # no answer is not a yes

    async def _past_turns(self, user, language_code: str) -> list[dict]:
        try:
            return list(await asyncio.to_thread(self.transcripts.recent, user.id, language_code=language_code))
        except Exception as exc:
            logger.warning("earlier transcripts unavailable error=%s", type(exc).__name__)
            return []

    async def _keep_transcripts(self, session: VoiceSession) -> None:
        """FR-3.11: hand the turns over once; the learner module stores them only if both consents still stand."""
        turns, session.kept_turns = session.kept_turns, []
        if not turns or self.transcripts is None:
            return
        ticket = session.ticket
        try:
            kept = await asyncio.to_thread(
                self.transcripts.keep, session.user.id, session_id=session.id, language_code=ticket.language_code,
                library_item_id=ticket.library_item_id, topic=ticket.topic, turns=turns)
        except Exception as exc:
            logger.warning("transcripts could not be kept error=%s", type(exc).__name__)
            return
        if kept and self.consolidator is not None:
            # Phase 5: the agent's notes are brought up to date from the turns just kept (their evidence), later.
            self.consolidator.later(session.user.id, language_code=ticket.language_code,
                                    support_language_code=ticket.support_language_code, session_id=session.id,
                                    turns=[KeptTurnText(turn.turn_index, turn.learner_text) for turn in turns])

    async def _finish_scoring(self, session: VoiceSession) -> None:
        if session.pron_tasks:
            _, pending = await asyncio.wait(session.pron_tasks, timeout=8 if session.consented else 0)
            for task in pending:
                task.cancel()
        if not session.consented:
            session.pron_results.clear()
        session.audio.clear()
        session.turn_audio = None

    async def _recurring_errors(self, user, language_code: str) -> list[str]:
        if self.signals is None:
            return []
        try:
            return await asyncio.to_thread(self.signals.recurring, user.id, language_code=language_code)
        except Exception as exc:
            logger.warning("recurring error kinds unavailable error=%s", type(exc).__name__)
            return []

    async def _remember_signals(self, session: VoiceSession) -> None:
        """Closed-code personalization signals only: error kinds, interests, goals, pace and turn length."""
        language = session.ticket.language_code
        found = [("error_type", code) for code in session.error_codes]
        found += [("topic", code) for code in session.interests] + [("goal", code) for code in session.goals]
        pace = pace_code(session.speech_units, session.speech_ms, language)
        length = turn_length_code(session.turn_sizes, language)
        found += [("pace", pace)] if pace else []
        found += [("turn_length", length)] if length else []
        if self.signals is None or not found:
            return
        try:
            await asyncio.to_thread(self.signals.record, session.user.id, language_code=language, signals=found)
        except Exception as exc:
            logger.warning("signals could not be remembered error=%s", type(exc).__name__)

    async def _finish(self, session: VoiceSession) -> list:
        """Wrap-up: what the learner allowed is remembered; the follow-ups for today's plan are returned."""
        # Revoking consent stops analysis, scoring and remembering, even for a conversation already running.
        session.consented = await self._has_consent(session.user)
        await self._finish_scoring(session)
        ticket = session.ticket
        if session.consented:
            await self._remember_signals(session)
            await self._keep_transcripts(session)
            await asyncio.to_thread(record_pronunciation, self.scores, session.user.id,
                                    language_code=ticket.language_code, source="conversation",
                                    results=list(session.pron_results))
            if session.learner_turns:
                seconds = session.spoken_ms // 1000  # what the learner said, not how long the call lasted
                await asyncio.to_thread(
                    log_activity, self.learning_log, user_id=session.user.id, language_code=ticket.language_code,
                    client_event_id=f"speaking_session:{session.id}", kind="speaking_session",
                    outcome="done", source_type="agent_session", source_id=str(session.id),
                    detail={"turns": session.learner_turns, "channel": "voice", "seconds": seconds,
                            "reuse_words": session.reuse_words[:6],
                            "corrections": session.corrections, "mode": session.mode,
                            "auto_hints": session.scaffolding.auto_hints})
        session.kept_turns = []  # without consent at the end nothing of them is kept
        if session.consented and self.session_events is not None and session.analysis_turns \
                and session.end_reason not in {"policy", "invalid_audio"}:
            try:
                data = await asyncio.wait_for(asyncio.to_thread(self._analysis_text, session), timeout=5)
                if data is not None:  # None: no saved word was said, so nothing to check and no model call
                    session.analysis = await asyncio.wait_for(
                        asyncio.to_thread(self.session_events.submit, data), timeout=5,
                    )
            except asyncio.TimeoutError:
                # The thread may still complete. Poll this ID rather than claim failure or enqueue again.
                session.analysis = {"session_id": str(session.id), "status": "queued"}
            except Exception:
                logger.warning("speaking analysis context could not be submitted")
                session.analysis = {"session_id": str(session.id), "status": "unavailable"}
        if session.transient:
            return []
        try:
            return await asyncio.to_thread(self.setup.end_conversation, session.user, session.prepared,
                                           list(session.history), session.day)
        except Exception as exc:
            logger.warning("realtime end of conversation failed error=%s", type(exc).__name__)
            return []

    def _analysis_text(self, session: VoiceSession) -> SessionText | None:
        """The words to check: the selected ones plus every other saved word the learner said."""
        ticket = session.ticket
        selected = [LearnedItem(item.item_id, item.text, "vocabulary", item.meaning, "selected", tuple(item.forms))
                    for item in ticket.items] if session.transient else []
        catalog = self.setup.target_catalog
        try:
            saved = list(catalog.saved_items(session.user.id, language_code=ticket.language_code,
                                             support_language_code=ticket.support_language_code)) if catalog else []
        except Exception:
            if not selected:
                raise
            logger.warning("saved words could not be read; checking only the selected words")
            saved = []
        targets = saved_word_targets(saved, session.analysis_turns, ticket.language_code, selected=selected)
        if not targets:
            return None
        return SessionText(
            id=session.id, user_id=session.user.id, language_code=ticket.language_code,
            library_item_id=ticket.library_item_id,
            context_key=("video:" + str(ticket.library_item_id) if ticket.library_item_id
                         else "home:" + ticket.topic[:100].casefold()),
            ended_at=datetime.now(UTC),
            targets=[SelectedWord(concept_id=UUID(item.concept_id), text=item.text, meaning=item.meaning,
                                  forms=list(item.forms)) for item in targets],
            turns=turns_with_server_support(session.analysis_turns, session.examples, targets,
                                            ticket.language_code),
            examples=session.examples,
        )

    async def _refuse(self, channel: ClientChannel, code: int, error: str, message: str) -> None:
        await self._safe(channel.send_json({"type": "error", "code": error, "message": message}))
        await self._safe(channel.close(code))

    @staticmethod
    async def _safe(action) -> None:
        try:
            await action
        except Exception:
            pass  # the learner may already have gone

    def _trace(self, session: VoiceSession) -> None:
        """Content-free: durations, counts and outcome codes only."""
        logger.info(
            "agent_voice_trace entry=%s mode=%s language=%s end=%s breach=%s slips=%s turns=%s hints=%s auto_hints=%s "
            "corrections=%s study_requests=%s rejected_calls=%s help=%s audio_in_s=%.1f audio_out_s=%.1f "
            "session_s=%.1f resumes=%s reattaches=%s model=%s prompt=%s",
            session.ticket.entry.value, session.mode, session.ticket.language_code, session.end_reason,
            session.breach, session.language_slips, session.turns, session.hints, session.scaffolding.auto_hints, session.corrections,
            session.study_requests, session.rejected_calls, session.help_requests, session.audio_in_s,
            session.audio_out_s, time.monotonic() - session.started, session.resumes, session.reattaches,
            getattr(self.voice, "model_name", None),
            VOICE_PROMPT_VERSION,
        )


def _voiced(frame: bytes) -> bool:
    try:
        return voice_activity(SpeechAudio(frame)).speech_ms >= MIN_FRAME_SPEECH_MS
    except Exception:
        return False

