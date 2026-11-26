"""Composition of the agent: the learner facts it reads, and the voice channel.

Channels are configured by AGENT_CHANNELS ("text", "voice"). Voice is refused outside development and test and
then only the listed learner IDs may start a session. The provider adapter authenticates with Application
Default Credentials. The text channel is composed in `speaking.py` (`get_companion_service`).
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from uuid import UUID

from app.bootstrap.wiring.activity import build_activity_service
from app.bootstrap.wiring.identity import get_jwt_verifier
from app.modules.learning.application.agent.voice import RealtimeGate, VoiceChannel, VoicePolicy
from app.modules.learning.domain.realtime import RealtimeLimits
from app.modules.learning.infrastructure.speech.gemini_live import GeminiLiveVoice
from app.platform.config import settings
from app.platform.observability.port import NoopTracing, TurnTracing

logger = logging.getLogger(__name__)

_VOICE_ENVIRONMENTS = {"development", "test"}


def agent_channels() -> frozenset[str]:
    return frozenset(part.strip() for part in settings.AGENT_CHANNELS.split(",") if part.strip())


def realtime_limits() -> RealtimeLimits:
    return RealtimeLimits(
        max_session_seconds=settings.COMPANION_REALTIME_MAX_SESSION_SECONDS,
        daily_seconds_per_learner=settings.COMPANION_REALTIME_DAILY_SECONDS,
        max_concurrent_sessions=settings.COMPANION_REALTIME_MAX_CONCURRENT,
        end_of_turn_silence_ms=settings.COMPANION_REALTIME_SILENCE_MS,
    )


def voice_policy() -> VoicePolicy:
    allowed = set()
    for value in settings.COMPANION_REALTIME_ALLOWED_USERS.split(","):
        try:
            allowed.add(UUID(value.strip()))
        except ValueError:
            continue
    enabled = "voice" in agent_channels() and settings.ENVIRONMENT in _VOICE_ENVIRONMENTS
    return VoicePolicy(enabled=enabled, allowed_user_ids=frozenset(allowed), limits=realtime_limits())


@lru_cache(maxsize=1)
def _realtime_gate() -> RealtimeGate:
    """Voice limits shared through the Redis of REDIS_URL when it is set (counts only); else this process's memory."""
    if not settings.REDIS_URL:
        return RealtimeGate(realtime_limits())
    from app.bootstrap.wiring.clients import redis_client
    from app.modules.learning.infrastructure.agent_state import RedisGateStore
    return RealtimeGate(realtime_limits(), store=RedisGateStore(redis_client(settings.REDIS_URL)))


@lru_cache(maxsize=1)
def _realtime_voice() -> GeminiLiveVoice | None:
    project = settings.COMPANION_REALTIME_PROJECT or settings.VERTEX_PROJECT_ID
    if not voice_policy().enabled or not project:
        return None
    return GeminiLiveVoice(project=project, region=settings.COMPANION_REALTIME_REGION,
                           model=settings.COMPANION_REALTIME_MODEL)


class VoiceConsent:
    """The learner's stored voice consent (learner module), read for every voice session."""

    def __init__(self, signals):
        self.signals = signals

    def has_consent(self, user_id) -> bool:
        return self.signals.has_consent(user_id)


class PersonalizationSignals:
    """Bridges the conversation to the learner's stored signals. Nothing is read or stored unless the voice
    consent is granted, and only closed codes pass (the signals service drops anything else)."""

    MIN_SIGHTINGS = 2  # an error kind seen in at least two sessions is one the agent pays extra attention to

    def __init__(self, signals):
        self.signals = signals

    def record(self, user_id, *, language_code: str, signals) -> None:
        from app.modules.learner.domain.agent_signals import SignalKind
        for kind, code in signals:
            try:
                self.signals.record(user_id, language_code=language_code, kind=SignalKind(kind), code=code)
            except ValueError:
                continue

    def recurring(self, user_id, *, language_code: str) -> list[str]:
        if not self.signals.has_consent(user_id):
            return []
        rows = [row for row in self.signals.signals(user_id).signals
                if row.kind.value == "error_type" and row.language_code == language_code
                and row.usage_count >= self.MIN_SIGHTINGS]
        return [row.code for row in sorted(rows, key=lambda row: -row.usage_count)][:3]


class SpeechTranscripts:
    """FR-3.11: hands a conversation's kept turns to the learner module, which stores them only while the learner's
    voice consent and transcript consent are both granted, and reads the learner's recent turns back as the agent's
    memory under the same two consents. Text and Azure word scores; never audio, never logged."""

    def __init__(self, transcripts):
        self.transcripts = transcripts

    def may_keep(self, user_id) -> bool:
        return self.transcripts.may_keep(user_id)

    def recent(self, user_id, *, language_code) -> list[dict]:
        """The learner's own recent turns for the agent's memory: what they said and the first correction."""
        return [{"said": row.learner_text,
                 "correction": ({"quote": row.grammar_errors[0].quote, "suggestion": row.grammar_errors[0].suggestion}
                                if row.grammar_errors else None)}
                for row in self.transcripts.recent_for_agent(user_id, language_code=language_code)]

    def recall(self, user_id, refs) -> list[dict]:
        """The kept turns an agent note came from: what the learner said and what the agent had said before it."""
        return [{"said": row.learner_text, "you_said": row.agent_text, "when": row.occurred_at.date().isoformat()}
                for row in self.transcripts.turns_for_agent(user_id, refs)]

    def keep(self, user_id, *, session_id, language_code, library_item_id, topic, turns) -> int:
        from app.modules.learner.domain.speech_transcripts import MAX_WORD_SCORES, TranscriptTurn
        rows = []
        for turn in turns:
            result = turn.pronunciation
            rows.append(TranscriptTurn(
                session_id=session_id, turn_index=turn.turn_index, language_code=language_code,
                library_item_id=library_item_id, topic=topic, assistance_level=turn.assistance_level,
                agent_text=turn.agent_text or None, learner_text=turn.learner_text,
                recognized_text=(result.recognized_text or None) if result is not None else None,
                word_scores=[{"word": word.word[:80], "accuracy": word.accuracy, "error_type": word.error_type.value}
                             for word in (result.words if result is not None else ())
                             if word.word.strip()][:MAX_WORD_SCORES],
                grammar_errors=turn.grammar_errors, occurred_at=turn.occurred_at))
        return self.transcripts.keep(user_id, rows)


# --- What the agent may read about the learner (the AgentFacts port) ----------------------------

_DETAIL_KEYS = ("text", "total", "correct", "missed", "accuracy", "scenario", "turns", "channel", "band", "rating")
_BRIEF_SECONDS = 300
_BRIEF_MAX_ENTRIES = 1000


# The usage ladder (learner/domain/ladder.py) as the agent reads it with a due word: how to bring it back.
RUNG_LABELS = {0: "seen", 1: "recognised", 2: "recalled", 3: "used with help", 4: "used alone",
               5: "used alone on different days and in different contexts"}


class LearnerFacts:
    """Reads for one learner and one language at a time, over the activity, review, content and learner data.

    Rows are short: kind, outcome, score, the word or grammar point they were about, when, and a few detail
    values. Never another learner's rows; never free text beyond what the learner looked up.
    """

    def __init__(self, *, activity, decks, concepts, brief, grammar_points, grammar_menu, declared_level=None,
                 grammar_titles=None, saved=None):
        self.activity = activity  # ActivityService
        self.decks = decks  # ReviewDeckRepository
        self.concepts = concepts  # ConceptRepository
        self._brief = brief  # (user_id, language) -> str
        self._grammar_points = grammar_points  # (language, support) -> set of approved point keys
        self._grammar_menu = grammar_menu  # (user_id, language, support) -> LessonMenu | None
        self._declared_level = declared_level  # (user_id, language) -> str | None
        self._grammar_titles = grammar_titles  # (language, support) -> {point key: title}
        self.saved = saved  # SavedConceptRepository: the usage rung (R0-R5) of each saved word; None = not shown

    def profile_brief(self, user_id, language_code: str) -> str:
        return self._brief(user_id, language_code)

    def declared_level(self, user_id, language_code: str) -> str | None:
        return self._declared_level(user_id, language_code) if self._declared_level else None

    def recent_activity(self, user_id, language_code: str, *, kind, since, limit: int) -> list[dict]:
        rows = self.activity.recent(user_id, language_code=language_code, since=since,
                                    kinds=[kind] if kind else None, limit=limit)
        return self._rows(rows)

    def region_activity(self, user_id, region_id: str, *, limit: int) -> list[dict]:
        rows = self.activity.for_source(user_id, source_type="video_region", source_id=region_id, limit=limit)
        return self._rows(rows)

    def due_counts(self, user_id) -> dict[str, int]:
        return {deck["language_code"]: deck["due_count"] for deck in self.decks.deck_counts(user_id)
                if deck["due_count"] > 0}

    def due_cards(self, user_id, language_code: str, *, limit: int) -> list[dict]:
        rows = [row for row in self.decks.deck_cards(user_id, language_code, limit=limit, concept_ids=None)
                if not row["is_new"]]
        texts = self._texts([str(row["concept_id"]) for row in rows])
        rungs = self._rungs(user_id, language_code)
        return [{"id": str(row["concept_id"]), "text": texts[str(row["concept_id"])],
                 **({"use": RUNG_LABELS[rungs[str(row["concept_id"])]]} if str(row["concept_id"]) in rungs else {})}
                for row in rows if str(row["concept_id"]) in texts]

    def _rungs(self, user_id, language_code: str) -> dict[str, int]:
        """How far the learner has got with each saved word (the usage ladder: days and contexts of their own use)."""
        if self.saved is None:
            return {}
        try:
            rows = self.saved.list_for_user(user_id, language_code=language_code)
        except Exception as exc:
            logger.warning("word rungs unavailable error=%s", type(exc).__name__)
            return {}
        return {str(row["concept_id"]): min(5, max(0, int(row.get("rung") or 0))) for row in rows
                if row.get("concept_id")}

    def owned_saved_ids(self, user_id, language_code: str, concept_ids: list[UUID]) -> list[str]:
        """The ids that are this learner's saved words in this language (the deck query is scoped to both)."""
        rows = self.decks.deck_cards(user_id, language_code, limit=len(concept_ids), concept_ids=concept_ids)
        return [str(row["concept_id"]) for row in rows]

    def study_requests(self, user_id, language_code: str, *, limit: int) -> list[dict]:
        rows = self.activity.study_requests(user_id, language_code=language_code, status="open", limit=limit)
        texts = self._texts([row.item_id for row in rows if row.item_type == "concept"])
        return [{"kind": row.kind, "item": texts.get(row.item_id, row.item_id), "reason": row.reason,
                 "created": row.created_at.date().isoformat()} for row in rows]

    def open_requests(self, user_id, language_code: str, support_language_code: str, *, limit: int = 10) -> list[dict]:
        """The learner's open requests in one language for the agent screen, newest first, each with the word or the
        grammar point's title (None when the item no longer exists)."""
        rows = self.activity.study_requests(user_id, language_code=language_code, status="open", limit=limit)
        words = self._texts([row.item_id for row in rows if row.item_type == "concept"])
        titles = self._grammar_titles(language_code, support_language_code) if self._grammar_titles else {}
        return [{"id": row.id, "kind": row.kind, "reason": row.reason, "created_at": row.created_at,
                 "title": words.get(row.item_id) if row.item_type == "concept" else titles.get(row.item_id)}
                for row in rows]

    def create_request(self, user_id, language_code: str, support_language_code, *, kind: str, item_id: str,
                       reason):
        if kind == "grammar_redo":
            exists = item_id in self._grammar_points(language_code, support_language_code or "vi")
        elif kind == "word_review":
            exists = self._concept_language(item_id) == language_code
        else:
            exists = False
        if not exists:
            return "invalid"
        _, created = self.activity.create_study_request(user_id, language_code=language_code, kind=kind,
                                                        item_id=item_id, reason=reason, created_by="agent")
        return "created" if created else "exists"

    def grammar_menu(self, user_id, language_code: str, support_language_code: str):
        return self._grammar_menu(user_id, language_code, support_language_code)

    def _concept_language(self, item_id: str) -> str | None:
        try:
            concept = self.concepts.get_by_id(UUID(item_id))
        except ValueError:
            return None
        return concept.language_code if concept else None

    def _texts(self, concept_ids: list[str]) -> dict[str, str]:
        wanted = []
        for value in dict.fromkeys(concept_ids):
            try:
                wanted.append(UUID(value))
            except (TypeError, ValueError):
                continue
        if not wanted:
            return {}
        return {str(concept.id): concept.canonical_text for concept in self.concepts.list_by_ids(wanted)}

    def _rows(self, rows) -> list[dict]:
        texts = self._texts([row.item_id for row in rows if row.item_type == "concept"])
        found = []
        for row in rows:
            item = texts.get(row.item_id) if row.item_type == "concept" else row.item_id \
                if row.item_type == "grammar_point" else None
            detail = {key: row.detail[key] for key in _DETAIL_KEYS if key in row.detail}
            if isinstance(detail.get("missed"), list):
                detail["missed"] = detail["missed"][:5]
            if isinstance(detail.get("text"), str):
                detail["text"] = detail["text"][:80]
            found.append({"kind": row.kind, "outcome": row.outcome, "score": row.score, "item": item,
                          "when": row.occurred_at.isoformat(timespec="minutes"),
                          **({"segment_id": row.item_id} if row.item_type == "segment" else {}),
                          **({"detail": detail} if detail else {})})
        return found


def _profile_brief():
    """(user_id, language_code) -> the learner profile brief (counts and closed codes only), cached a few minutes
    per learner and language so a text conversation does not rebuild it on every turn."""
    from app.bootstrap.wiring.learner_profile import get_learner_profile_snapshot_service
    from app.modules.identity.contracts import CurrentUser

    service = get_learner_profile_snapshot_service()
    cache: dict[tuple, tuple[float, str]] = {}

    def brief(user_id, language_code):
        key, now = (user_id, language_code), time.monotonic()
        cached = cache.get(key)
        if cached is not None and now - cached[0] < _BRIEF_SECONDS:
            return cached[1]
        text = service.snapshot(CurrentUser(id=user_id), language_code).brief()
        if len(cache) >= _BRIEF_MAX_ENTRIES:
            cache.clear()
        cache[key] = (now, text)
        return text

    return brief


def build_learner_facts(client) -> LearnerFacts:
    from app.modules.content.infrastructure.grammar_banks import GrammarBanks
    from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
    from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
    from app.modules.learner.infrastructure.user_language_preferences import UserLanguagePreferenceRepository
    from app.modules.learning.domain.lesson_menu import build_lesson_menu
    from app.modules.practice.infrastructure.repositories import ReviewDeckRepository

    banks, preferences = GrammarBanks(), UserLanguagePreferenceRepository(client)

    def grammar_points(language: str, support: str) -> set[str]:
        return {point.key for bank in banks.for_language(language, support) for point in bank.points}

    def grammar_titles(language: str, support: str) -> dict[str, str]:
        return {point.key: point.title for bank in banks.for_language(language, support) for point in bank.points}

    def grammar_menu(user_id, language_code, support_language_code):
        preference = preferences.get_by_language_for_user(user_id=user_id, language_code=language_code)
        return build_lesson_menu(banks.for_language(language_code, support_language_code or "vi"),
                                 preference.declared_level if preference else None)

    def declared_level(user_id, language_code):
        preference = preferences.get_by_language_for_user(user_id=user_id, language_code=language_code)
        return preference.declared_level if preference else None

    return LearnerFacts(activity=build_activity_service(client), decks=ReviewDeckRepository(client),
                        concepts=ConceptRepository(client), brief=_profile_brief(),
                        grammar_points=grammar_points, grammar_menu=grammar_menu, declared_level=declared_level,
                        grammar_titles=grammar_titles, saved=SavedConceptRepository(client))


@lru_cache(maxsize=1)
def get_learner_facts() -> LearnerFacts:
    from app.bootstrap.wiring.clients import service_client
    return build_learner_facts(service_client())


@lru_cache
def get_memory_consolidator():
    """Phase 5: the agent's notes from a conversation's kept turns, one background thread per process; None when no
    language model is configured. Each run checks the day's AI budget first."""
    from app.bootstrap.wiring.speaking import _language_model
    from app.modules.learning.application.agent.memory_consolidation import MemoryConsolidator
    from app.platform.ai_budget import daily_budget
    model = _language_model(settings.COMPANION_MODEL or settings.SPEAKING_COACH_MODEL)
    if model is None:
        return None
    return MemoryConsolidator(model, get_agent_memory(), allows=lambda: daily_budget().allows())


@lru_cache(maxsize=1)
def get_agent_memory():
    """What the agent remembers across conversations: one repository (service role, learner named on every query)."""
    from app.bootstrap.wiring.clients import service_client
    from app.modules.learning.infrastructure.agent_memory import AgentMemoryRepository
    return AgentMemoryRepository(service_client())


@lru_cache(maxsize=1)
def get_context_builder():
    """One ContextBuilder for the text channel's requests: a conversation does not rebuild the context every turn."""
    from app.modules.learning.application.agent.context import ContextBuilder
    return ContextBuilder(get_learner_facts(), memory=get_agent_memory())


def _today_tasks():
    """(user, day) -> what the learner could do today, for the agent's show_tasks."""
    from datetime import UTC, datetime
    from app.bootstrap.wiring.study_plan import get_study_plan_service

    service = get_study_plan_service()

    def tasks(user, day):
        plan = service.today(user, day or datetime.now(UTC).date())
        return [item.model_dump(mode="json") for item in plan.items
                if item.status == "open" and item.kind != "conversation"][:3]

    return tasks


@lru_cache(maxsize=1)
def get_plan_editor():
    """Adds or removes one of today's tasks for the agent: the study-plan service, built once."""
    from app.bootstrap.wiring.study_plan import get_study_plan_service
    return get_study_plan_service()


class VideoRegions:
    """Checks a study region the agent wants to open: an own Library video, and a region whose two ends are sentences
    of its current original transcript, in order and within the length a region may have. Read-only."""

    def __init__(self, *, library, videos, transcripts, segments):
        self.library, self.videos, self.transcripts, self.segments = library, videos, transcripts, segments

    def check(self, user_id, library_item_id, region_id: str):
        from app.kernel.region_ids import split_region_id
        from app.modules.content.domain.workspace import MAX_REGION_SEGMENTS
        from app.modules.learning.application.agent.ports import RegionTarget
        ends = split_region_id(region_id)
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user_id) if ends else None
        video = self.videos.get_by_id(association.video_id) if association is not None else None
        track = next((row for row in self.transcripts.list_for_video(video.id)
                      if row.is_original and row.language_code == video.original_language_code), None) if video else None
        if track is None:
            return None
        start, end = (self.segments.get_by_id(segment_id) for segment_id in ends)
        if (start is None or end is None or not start.transcript_id == end.transcript_id == track.id
                or end.sequence_number < start.sequence_number
                or end.sequence_number - start.sequence_number + 1 > MAX_REGION_SEGMENTS):
            return None
        return RegionTarget(title=" ".join((video.title or "").split())[:200] or None, start_ms=start.start_ms)


def get_video_regions() -> VideoRegions:
    from app.bootstrap.wiring.clients import service_client
    from app.modules.content.infrastructure.repositories.learner_videos import LearnerVideoRepository
    from app.modules.content.infrastructure.repositories.transcript_segments import TranscriptSegmentRepository
    from app.modules.content.infrastructure.repositories.video_transcripts import VideoTranscriptRepository
    from app.modules.content.infrastructure.repositories.videos import VideoRepository
    client = service_client()
    return VideoRegions(library=LearnerVideoRepository(client), videos=VideoRepository(client),
                        transcripts=VideoTranscriptRepository(client), segments=TranscriptSegmentRepository(client))


class _Lazy:
    """Builds its target on first use, so composing a channel never opens the study-plan or content clients."""

    def __init__(self, factory):
        self._factory = factory

    def __getattr__(self, name):
        return getattr(self._factory(), name)


def lazy_plan_editor() -> _Lazy:
    return _Lazy(get_plan_editor)


def lazy_video_regions() -> _Lazy:
    return _Lazy(get_video_regions)


@lru_cache(maxsize=1)
def get_text_turn_tracing() -> TurnTracing:
    if not settings.LANGFUSE_ENABLED:
        return NoopTracing()
    if not (settings.LANGFUSE_HOST and settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        logger.warning("Langfuse tracing configuration is incomplete")
        return NoopTracing()
    try:
        from app.platform.observability.langfuse import LangfuseTracing, create_client

        client = create_client(host=settings.LANGFUSE_HOST,
                               public_key=settings.LANGFUSE_PUBLIC_KEY.get_secret_value(),
                               secret_key=settings.LANGFUSE_SECRET_KEY.get_secret_value())
        return LangfuseTracing(client, capture_content=settings.LANGFUSE_CAPTURE_CONTENT)
    except Exception:
        logger.warning("Langfuse tracing client could not be initialized")
        return NoopTracing()


def lazy_text_turn_tracing() -> TurnTracing:
    return _Lazy(get_text_turn_tracing)


def get_voice_agent_service() -> VoiceChannel:
    from app.bootstrap.wiring.clients import service_client
    from app.bootstrap.wiring.learner import get_agent_signals_service, get_speech_transcripts_service
    from app.bootstrap.wiring.session_events import get_session_events_service
    from app.bootstrap.wiring.speaking import _pronunciation_assessor, get_companion_service
    from app.modules.learning.infrastructure.speaking_activity import PronunciationScoreRepository
    return VoiceChannel(
        session_events=get_session_events_service(), pronunciation=_pronunciation_assessor(),
        signals=PersonalizationSignals(get_agent_signals_service()),
        consent=VoiceConsent(get_agent_signals_service()),
        transcripts=SpeechTranscripts(get_speech_transcripts_service()),
        setup=get_companion_service(), voice=_realtime_voice(), gate=_realtime_gate(),
        verifier=get_jwt_verifier(), policy=voice_policy(),
        tasks=_today_tasks(), scores=PronunciationScoreRepository(service_client()),
        learning_log=build_activity_service(service_client()), facts=get_learner_facts(),
        memory=get_agent_memory(), consolidator=get_memory_consolidator(),
        plan=lazy_plan_editor(), video_regions=lazy_video_regions(),
    )
