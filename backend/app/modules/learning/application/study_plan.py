"""Daily study plan: composed on the first open of the day, then read as stored.

The server picks the proposals from signals it already trusts; a model may only rewrite their
wording, and any failure falls back to fixed Vietnamese templates. Accepting a proposal records
the learner's choice after rechecking ownership; the client then opens the existing resource
through its own endpoint. No learner state is read for grading or written here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Callable, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.learning.application.speaking_ports import StructuredTextModel
from app.modules.learning.application.study_plan_prompts import (
    STUDY_PLAN_PROMPT_VERSION,
    STUDY_PLAN_SYSTEM_PROMPT,
    PlanTextOutput,
    build_study_plan_prompt,
)
from app.modules.learning.domain.study_plan import (
    AGENT_ADDABLE_KINDS,
    MAX_INTRO_CHARS,
    PlanItemDraft,
    PlanItemKind,
    PlanItemStatus,
    PlanSignals,
    PlanVideo,
    acceptable_text,
    compose_added_item,
    compose_follow_ups,
    compose_plan,
    template_intro,
    with_reasons,
)

logger = logging.getLogger(__name__)

MAX_ERROR_NOTES = 2


class StudyPlanError(Exception):
    """Learner-safe failure; ``kind`` maps to HTTP in the API layer."""

    def __init__(self, kind: str, code: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.code = code


# --- Ports -----------------------------------------------------------------------------

class ReviewReadiness(Protocol):
    def ready_count(self, user, *, language_code: str) -> int: ...


class SavedWordCount(Protocol):
    def saved_to_practise(self, user, *, language_code: str) -> int: ...


@dataclass(frozen=True)
class StoredPlanItem:
    id: UUID
    plan_day: date
    position: int
    kind: PlanItemKind
    status: PlanItemStatus
    minutes: int
    reason: str
    library_item_id: UUID | None = None
    video_title: str | None = None
    companion_entry: str | None = None
    item_count: int | None = None


@dataclass(frozen=True)
class StoredPlan:
    id: UUID
    plan_day: date
    language_code: str
    intro: str
    items: tuple[StoredPlanItem, ...]


class ResumeReader(Protocol):
    """The video the learner last stopped in (content module data), or None."""

    def latest(self, user) -> object | None: ...


class StudyPlanStore(Protocol):
    def get_plan(self, user_id: UUID, *, language_code: str, plan_day: date) -> StoredPlan | None: ...

    def create_plan(self, user_id: UUID, *, language_code: str, plan_day: date, intro: str, text_source: str,
                    model: str | None, prompt_version: str | None, items: list[PlanItemDraft]) -> UUID: ...

    def get_item(self, user_id: UUID, item_id: UUID) -> StoredPlanItem | None: ...

    def append_items(self, user_id: UUID, plan_id: UUID, items: list[PlanItemDraft]) -> list[UUID]:
        """Add proposals to an existing plan; items it already holds are skipped."""
        ...

    def decide(self, user_id: UUID, item_id: UUID, *, status: PlanItemStatus) -> bool:
        """Compare-and-swap from ``open``; False when the item was no longer open."""
        ...


# --- Views -----------------------------------------------------------------------------

class StudyPlanItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: PlanItemKind
    status: PlanItemStatus
    minutes: int
    reason: str
    item_count: int | None
    library_item_id: UUID | None
    video_title: str | None
    companion_entry: str | None


class YesterdaySpeaking(BaseModel):
    """What the learner did in speaking yesterday: counts and the names of their own saved words only."""

    model_config = ConfigDict(extra="forbid")

    sessions: int
    minutes: int
    turns: int
    reuse_words: list[str]


class StudyPlanView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    day: date
    language_code: str
    intro: str
    items: list[StudyPlanItemView]
    yesterday: YesterdaySpeaking | None = None  # FR-3.10: the "end of day" greeting at Home the next day


def summarize_yesterday(rows, *, today: date, utc_offset_minutes: int) -> YesterdaySpeaking | None:
    """The learner's speaking sessions of local yesterday, as counts and up to six word names."""
    offset = timedelta(minutes=utc_offset_minutes)
    sessions, seconds, turns, words = 0, 0, 0, []
    for entry in sorted(rows, key=lambda item: str(item.get("occurred_at"))):
        when = datetime.fromisoformat(str(entry["occurred_at"]).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if (when + offset).date() != today - timedelta(days=1):
            continue
        sessions += 1
        seconds += int(entry.get("seconds") or 0)
        turns += int(entry.get("turns") or 0)
        words += [word for word in (entry.get("reuse_words") or [])
                  if isinstance(word, str) and 0 < len(word.strip()) <= 60]
    if sessions == 0:
        return None
    return YesterdaySpeaking(sessions=sessions, minutes=-(-seconds // 60), turns=turns,
                             reuse_words=list(dict.fromkeys(word.strip() for word in words))[:6])


def _item_view(item: StoredPlanItem) -> StudyPlanItemView:
    return StudyPlanItemView(
        id=item.id, kind=item.kind, status=item.status, minutes=item.minutes, reason=item.reason,
        item_count=item.item_count, library_item_id=item.library_item_id, video_title=item.video_title,
        companion_entry=item.companion_entry,
    )


def _same_target(item: StoredPlanItem, draft: PlanItemDraft) -> bool:
    return (item.kind == draft.kind and item.library_item_id == draft.library_item_id
            and item.companion_entry == draft.companion_entry)


@dataclass(frozen=True)
class PlanEdit:
    """What one agent edit changed: the item and which way (`added`, or `removed` = dismissed)."""

    change: Literal["added", "removed"]
    item_id: UUID
    kind: str
    minutes: int
    video_title: str | None = None


def _edit(change: Literal["added", "removed"], item: StoredPlanItem) -> PlanEdit:
    return PlanEdit(change=change, item_id=item.id, kind=item.kind.value, minutes=item.minutes,
                    video_title=item.video_title)


class PlanEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change: Literal["added", "removed"]


# --- Service ---------------------------------------------------------------------------

class StudyPlanService:
    def __init__(self, *, preferences, library, videos, reviews: ReviewReadiness, saved_words: SavedWordCount,
                 recurring, model: StructuredTextModel | None, store: StudyPlanStore,
                 resume: ResumeReader | None = None, speaking=None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.preferences = preferences
        self.library = library
        self.videos = videos
        self.reviews = reviews
        self.saved_words = saved_words
        # The learner's recurring kinds of grammar mistake (closed codes), only under their stored consent.
        self.recurring = recurring
        self.model = model
        self.store = store
        self.resume = resume
        self.speaking = speaking
        self.clock = clock

    def today(self, user, day: date, utc_offset_minutes: int = 0) -> StudyPlanView:
        """``day`` is the learner's local date; it only names the plan and must be near today (UTC)."""
        utc_today = self.clock().date()
        if abs((day - utc_today).days) > 1:
            raise StudyPlanError("invalid_input", "plan_day_invalid", "The plan day must be today.")
        language, support = self._languages(user)
        stored = self.store.get_plan(user.id, language_code=language, plan_day=day)
        if stored is None:
            signals, notes = self._signals(user, language)
            items = compose_plan(signals)
            intro, items, source = self._wording(items, signals, notes, language, support)
            self.store.create_plan(
                user.id, language_code=language, plan_day=day, intro=intro, text_source=source,
                model=self.model.model_name if source == "model" and self.model is not None else None,
                prompt_version=STUDY_PLAN_PROMPT_VERSION if source == "model" else None, items=items,
            )
            stored = self.store.get_plan(user.id, language_code=language, plan_day=day)
            if stored is None:
                raise StudyPlanError("unavailable", "plan_unavailable", "Your plan is not available right now.")
        return StudyPlanView(plan_id=stored.id, day=stored.plan_day, language_code=stored.language_code,
                             intro=stored.intro, items=[_item_view(item) for item in stored.items],
                             yesterday=self._yesterday(user, day, utc_offset_minutes, stored.language_code))

    def _yesterday(self, user, day: date, utc_offset_minutes: int, language: str) -> YesterdaySpeaking | None:
        """Best effort: the greeting is an extra, never a reason for the plan to fail."""
        if self.speaking is None:
            return None
        try:
            start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(days=1, minutes=utc_offset_minutes)
            return summarize_yesterday(self.speaking.rows_between(user.id, start, start + timedelta(days=1),
                                                                  language_code=language),
                                       today=day, utc_offset_minutes=utc_offset_minutes)
        except Exception as exc:
            logger.warning("study plan yesterday unavailable error=%s", type(exc).__name__)
            return None

    def decide(self, user, item_id: UUID, status: PlanItemStatus) -> StudyPlanItemView:
        if status == PlanItemStatus.OPEN:
            raise StudyPlanError("invalid_input", "plan_item_status_invalid", "Choose accept or dismiss.")
        item = self.store.get_item(user.id, item_id)
        if item is None:
            raise StudyPlanError("not_found", "plan_item_not_found", "This suggestion was not found.")
        if item.status == status:
            return _item_view(item)  # repeating the same choice is harmless
        if item.status != PlanItemStatus.OPEN:
            raise StudyPlanError("conflict", "plan_item_decided", "You already chose for this suggestion.")
        if (self.clock().date() - item.plan_day).days > 1:
            raise StudyPlanError("conflict", "plan_item_expired", "This suggestion is from an earlier day.")
        if status == PlanItemStatus.ACCEPTED and item.library_item_id is not None and self.library.get_for_user(
                library_item_id=item.library_item_id, user_id=user.id) is None:
            raise StudyPlanError("not_found", "plan_item_unavailable", "This video is no longer in your Library.")
        if not self.store.decide(user.id, item_id, status=status):
            current = self.store.get_item(user.id, item_id)
            if current is not None and current.status == status:
                return _item_view(current)
            raise StudyPlanError("conflict", "plan_item_decided", "You already chose for this suggestion.")
        updated = self.store.get_item(user.id, item_id)
        if updated is None:
            raise StudyPlanError("not_found", "plan_item_not_found", "This suggestion was not found.")
        return _item_view(updated)

    # --- Edits the agent makes for the learner (PRD 8.12 point 4) ---------------------------

    def add_item(self, user, day: date, *, kind: str, library_item_id: UUID | None = None) -> PlanEdit:
        """One proposal added to the day's existing plan (a dismissed one is reopened). Refusals raise StudyPlanError."""
        plan, language = self._edit_plan(user, day)
        try:
            item_kind = PlanItemKind(kind)
        except ValueError:
            item_kind = None
        if item_kind not in AGENT_ADDABLE_KINDS:
            raise StudyPlanError("invalid_input", "plan_kind_invalid", "This kind of task cannot be added.")
        video = self._owned_video_for_edit(user, library_item_id, language) if library_item_id else None
        if library_item_id and video is None:
            raise StudyPlanError("not_found", "plan_item_unavailable", "This video is not in your Library.")
        if item_kind == PlanItemKind.VIDEO_PRACTICE and video is None:
            raise StudyPlanError("invalid_input", "plan_video_required", "Choose a video for this task.")
        reviews = self.reviews.ready_count(user, language_code=language) if item_kind == PlanItemKind.REVIEW else 0
        saved = (self.saved_words.saved_to_practise(user, language_code=language)
                 if item_kind == PlanItemKind.MY_WORDS else 0)
        draft = compose_added_item(item_kind, reviews_ready=reviews, saved_words=saved, video=video)
        if draft is None:
            raise StudyPlanError("conflict", "plan_nothing_to_add", "There is nothing for this task yet.")
        same = next((item for item in plan.items if _same_target(item, draft)), None)
        if same is not None:
            if same.status == PlanItemStatus.DISMISSED and self.store.reopen(user.id, same.id):
                return _edit("added", same)
            raise StudyPlanError("conflict", "plan_item_exists", "This task is already in today's plan.")
        added = self.store.append_items(user.id, plan.id, [draft])
        stored = self.store.get_item(user.id, added[0]) if added else None
        if stored is None:
            raise StudyPlanError("conflict", "plan_full", "Today's plan is full.")
        return _edit("added", stored)

    def remove_item(self, user, day: date, *, kind: str, library_item_id: UUID | None = None) -> PlanEdit:
        """The first open proposal of this kind (and video) is dismissed. Refusals raise StudyPlanError."""
        plan, _ = self._edit_plan(user, day)
        match = next((item for item in plan.items if item.status == PlanItemStatus.OPEN and item.kind.value == kind
                      and (library_item_id is None or item.library_item_id == library_item_id)), None)
        if match is None:
            raise StudyPlanError("not_found", "plan_item_not_found", "That task is not in today's plan.")
        if not self.store.decide(user.id, match.id, status=PlanItemStatus.DISMISSED):
            raise StudyPlanError("conflict", "plan_item_decided", "You already chose for this task.")
        return _edit("removed", match)

    def undo_edit(self, user, item_id: UUID, change: str) -> StudyPlanItemView:
        """Reverses exactly one agent edit of one item: an added task is dismissed, a removed one is open again.
        Repeating it is harmless; a task the learner already started cannot be taken back."""
        item = self.store.get_item(user.id, item_id)
        if item is None:
            raise StudyPlanError("not_found", "plan_item_not_found", "This task was not found.")
        if (self.clock().date() - item.plan_day).days > 1:
            raise StudyPlanError("conflict", "plan_item_expired", "This task is from an earlier day.")
        if change == "added":
            if item.status == PlanItemStatus.OPEN:
                self.store.decide(user.id, item_id, status=PlanItemStatus.DISMISSED)
                item = self.store.get_item(user.id, item_id) or item
            if item.status == PlanItemStatus.ACCEPTED:
                raise StudyPlanError("conflict", "plan_item_decided", "You already started this task.")
        elif change == "removed":
            if item.status == PlanItemStatus.DISMISSED:
                self.store.reopen(user.id, item_id)
                item = self.store.get_item(user.id, item_id) or item
        else:
            raise StudyPlanError("invalid_input", "plan_edit_invalid", "Choose added or removed.")
        return _item_view(item)

    def _edit_plan(self, user, day: date) -> tuple[StoredPlan, str]:
        if abs((day - self.clock().date()).days) > 1:
            raise StudyPlanError("invalid_input", "plan_day_invalid", "The plan day must be today.")
        language, _ = self._languages(user)
        plan = self.store.get_plan(user.id, language_code=language, plan_day=day)
        if plan is None:  # an edit never composes a plan (no model call): Home does that on the first open
            raise StudyPlanError("conflict", "plan_not_ready", "Today's plan is not ready yet.")
        return plan, language

    def _owned_video_for_edit(self, user, library_item_id: UUID, language: str) -> PlanVideo | None:
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user.id)
        video = self.videos.get_by_id(association.video_id) if association is not None else None
        if (video is None or video.original_language_code != language or video.learning_status != "ready"
                or not (video.title or "").strip()):
            return None
        return PlanVideo(library_item_id=library_item_id, title=" ".join(video.title.split())[:300])

    # --- Composition inputs --------------------------------------------------------------

    def _signals(self, user, language: str) -> tuple[PlanSignals, list[str]]:
        # A failed read raises: a plan built on missing signals would be stored for the whole day.
        reviews_ready = self.reviews.ready_count(user, language_code=language)
        saved = self.saved_words.saved_to_practise(user, language_code=language)
        notes = self._error_notes(user, language)
        return PlanSignals(reviews_ready=reviews_ready, latest_video=self._latest_video(user, language),
                           saved_words=saved, has_recurring_error=bool(notes),
                           resume_video=self._resume_video(user, language)), notes

    def _latest_video(self, user, language: str) -> PlanVideo | None:
        associations = self.library.list_for_user(user.id, limit=50)
        videos = self.videos.get_many_by_ids(list(dict.fromkeys(item.video_id for item in associations)))
        for association in associations:  # newest Library item first
            video = videos.get(association.video_id)
            if (video is not None and video.original_language_code == language
                    and video.learning_status == "ready" and (video.title or "").strip()):
                return PlanVideo(library_item_id=association.id, title=" ".join(video.title.split())[:300])
        return None

    def _resume_video(self, user, language: str) -> PlanVideo | None:
        """The video the learner stopped in, only while it is still in their Library, ready, and in this
        language. It is a convenience: any problem here leaves the plan without it."""
        if self.resume is None:
            return None
        try:
            item = self.resume.latest(user)
            association = self.library.get_for_user(library_item_id=item.library_item_id, user_id=user.id) if item else None
            video = self.videos.get_many_by_ids([association.video_id]).get(association.video_id) if association else None
        except Exception as exc:
            logger.warning("study plan resume video unavailable error=%s", type(exc).__name__)
            return None
        if (video is None or video.original_language_code != language or video.learning_status != "ready"
                or not (video.title or "").strip()):
            return None
        return PlanVideo(library_item_id=item.library_item_id, title=" ".join(video.title.split())[:300])

    def _error_notes(self, user, language: str) -> list[str]:
        """Recurring kinds of mistake as closed codes (consent is checked by the reader); a problem here never
        blocks the plan."""
        if self.recurring is None:
            return []
        try:
            return list(self.recurring.recurring(user.id, language_code=language))[:MAX_ERROR_NOTES]
        except Exception as exc:
            logger.warning("study plan recurring errors unavailable error=%s", type(exc).__name__)
            return []

    def _wording(self, items: list[PlanItemDraft], signals: PlanSignals, notes: list[str], language: str,
                 support: str) -> tuple[str, list[PlanItemDraft], str]:
        intro = template_intro(signals)
        if self.model is None or not items:
            return intro, items, "template"
        try:
            output = self.model.generate_structured(
                build_study_plan_prompt(learning_language=language, support_language=support, items=items,
                                        error_notes=notes),
                PlanTextOutput, system_prompt=STUDY_PLAN_SYSTEM_PROMPT, temperature=0.4, max_tokens=600,
            )
        except Exception as exc:
            # Bodies are never logged; the plan keeps its template wording.
            logger.warning("study plan wording unavailable error=%s", type(exc).__name__)
            return intro, items, "template"
        reasons = {reason.index: reason.reason for reason in output.reasons if reason.index < len(items)}
        if not acceptable_text(output.intro, max_chars=MAX_INTRO_CHARS) or set(reasons) != set(range(len(items))):
            logger.warning("study plan wording rejected")
            return intro, items, "template"
        worded = with_reasons(items, reasons)
        return " ".join(output.intro.split()), worded, "model"

    def _languages(self, user) -> tuple[str, str]:
        profile = self.preferences.get_profile_for_user(user.id)
        if profile is None or not profile.language_code:
            raise StudyPlanError("conflict", "language_profile_required", "Choose your learning language first.")
        return profile.language_code, profile.support_language_code or "vi"


class ConversationFollowUpService:
    """Next steps added to the learner's plan for a day when a conversation ends.

    Best effort and cheap: it needs the day's plan to exist already (it never composes one, so no
    model call), counts review items due now in the learning language, and uses the conversation's
    video only while it is still in the learner's Library and ready. Any problem means no follow-ups.
    """

    def __init__(self, *, preferences, library, videos, reviews: ReviewReadiness, store: StudyPlanStore,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.preferences = preferences
        self.library = library
        self.videos = videos
        self.reviews = reviews
        self.store = store
        self.clock = clock

    def after_conversation(self, user, day: date | None, *, library_item_id: UUID | None) -> list[StudyPlanItemView]:
        if day is None or abs((day - self.clock().date()).days) > 1:
            return []
        try:
            profile = self.preferences.get_profile_for_user(user.id)
            language = profile.language_code if profile is not None else None
            plan = self.store.get_plan(user.id, language_code=language, plan_day=day) if language else None
            if plan is None:
                return []
            video = self._owned_video(user, library_item_id, language) if library_item_id else None
            drafts = compose_follow_ups(reviews_ready=self.reviews.ready_count(user, language_code=language),
                                        video=video)
            if not drafts:
                return []
            added = set(self.store.append_items(user.id, plan.id, drafts))
            stored = self.store.get_plan(user.id, language_code=language, plan_day=day)
        except Exception as exc:
            logger.warning("companion follow-ups unavailable error=%s", type(exc).__name__)
            return []
        return [_item_view(item) for item in (stored.items if stored else ()) if item.id in added]

    def _owned_video(self, user, library_item_id: UUID, language: str) -> PlanVideo | None:
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user.id)
        video = self.videos.get_by_id(association.video_id) if association is not None else None
        if (video is None or video.original_language_code != language or video.learning_status != "ready"
                or not (video.title or "").strip()):
            return None
        return PlanVideo(library_item_id=library_item_id, title=" ".join(video.title.split())[:300])
