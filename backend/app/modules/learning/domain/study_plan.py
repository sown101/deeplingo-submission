"""Daily study plan: which proposals a learner sees today, in which order.

The composition is deterministic: signals the server already trusts (reviews ready, the newest
ready video in the learner's Library, saved words, a consented recurring-error note) become at
most a few proposals under a small daily time budget. A model may only rewrite the reasons;
it never adds, removes or reorders proposals. Nothing here reads or writes learner state.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import Enum
from uuid import UUID

MAX_PROPOSALS = 3
DAILY_MINUTES = 15
MAX_REASON_CHARS = 160
MAX_INTRO_CHARS = 200

TEMPLATE_INTRO = "Hôm nay mình gợi ý vài việc ngắn. Bạn chọn việc nào cũng được nhé."
NEW_LEARNER_INTRO = "Chào bạn! Mình bắt đầu bằng một video bạn thích nhé."


class PlanItemKind(str, Enum):
    REVIEW = "review"
    CONVERSATION = "conversation"
    VIDEO_PRACTICE = "video_practice"
    MY_WORDS = "my_words"
    ADD_VIDEO = "add_video"


class PlanItemStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class PlanVideo:
    library_item_id: UUID
    title: str


@dataclass(frozen=True)
class PlanSignals:
    reviews_ready: int
    latest_video: PlanVideo | None
    saved_words: int
    has_recurring_error: bool = False
    # A video the learner stopped in (a saved position or study part); proposed before the newest one.
    resume_video: PlanVideo | None = None


@dataclass(frozen=True)
class PlanItemDraft:
    kind: PlanItemKind
    minutes: int
    reason: str
    library_item_id: UUID | None = None
    video_title: str | None = None
    companion_entry: str | None = None
    item_count: int | None = None


def compose_plan(signals: PlanSignals) -> list[PlanItemDraft]:
    """Ordered proposals: time-sensitive review first, then talking, then practice."""
    video = signals.latest_video
    candidates: list[PlanItemDraft] = []
    if video is None:
        candidates.append(PlanItemDraft(
            kind=PlanItemKind.ADD_VIDEO, minutes=3,
            reason="Thêm một video bạn thích để học từ nội dung thật."))
    if signals.reviews_ready > 0:
        count = signals.reviews_ready
        candidates.append(PlanItemDraft(
            kind=PlanItemKind.REVIEW, minutes=min(10, max(2, math.ceil(count / 2))), item_count=count,
            reason=f"{count} mục đã đến lúc ôn. Ôn đúng lúc giúp bạn nhớ lâu hơn."))
    if signals.resume_video is not None:
        resume = signals.resume_video
        candidates.append(PlanItemDraft(
            kind=PlanItemKind.VIDEO_PRACTICE, minutes=5, library_item_id=resume.library_item_id,
            video_title=resume.title,
            reason=f"Tiếp tục xem video “{_short(resume.title)}” từ chỗ bạn đã dừng."))
    elif video is not None:
        candidates.append(PlanItemDraft(
            kind=PlanItemKind.VIDEO_PRACTICE, minutes=5, library_item_id=video.library_item_id,
            video_title=video.title,
            reason=f"Xem video “{_short(video.title)}” và nói về nó với mình."))
    candidates.append(PlanItemDraft(
        kind=PlanItemKind.CONVERSATION, minutes=5, companion_entry="home",
        reason="Chọn một chủ đề bạn quan tâm rồi nói chuyện với mình, bằng giọng nói hoặc chữ."))
    if video is not None:
        reason = f"Nói chuyện về video “{_short(video.title)}” để dùng những từ bạn vừa gặp."
        if signals.has_recurring_error:
            reason += " Mình sẽ giúp bạn luyện lại lỗi hay gặp."
        candidates.append(PlanItemDraft(
            kind=PlanItemKind.CONVERSATION, minutes=5, companion_entry="video",
            library_item_id=video.library_item_id, video_title=video.title, reason=reason))
    if signals.saved_words > 0:
        candidates.append(PlanItemDraft(
            kind=PlanItemKind.MY_WORDS, minutes=3, item_count=signals.saved_words,
            reason=f"Bạn có {signals.saved_words} từ đã lưu đang chờ luyện."))

    chosen: list[PlanItemDraft] = []
    minutes = 0
    for item in candidates:
        if len(chosen) >= MAX_PROPOSALS:
            break
        if chosen and minutes + item.minutes > DAILY_MINUTES:
            continue
        chosen.append(item)
        minutes += item.minutes
    return chosen


MAX_FOLLOW_UPS = 2


def compose_follow_ups(*, reviews_ready: int, video: PlanVideo | None) -> list[PlanItemDraft]:
    """At most two next steps when a conversation ends, chosen by the server.

    Review comes first (it is time-sensitive); practising the video the learner just talked about
    comes second. The wording is a fixed template, so ending a conversation adds no model call.
    """
    items: list[PlanItemDraft] = []
    if reviews_ready > 0:
        items.append(PlanItemDraft(
            kind=PlanItemKind.REVIEW, minutes=min(10, max(2, math.ceil(reviews_ready / 2))),
            item_count=reviews_ready,
            reason=f"Sau cuộc trò chuyện, ôn {reviews_ready} mục đã đến hạn để giữ chắc những gì bạn vừa dùng."))
    if video is not None:
        items.append(PlanItemDraft(
            kind=PlanItemKind.VIDEO_PRACTICE, minutes=5, library_item_id=video.library_item_id,
            video_title=video.title,
            reason=f"Luyện tiếp các từ của video “{_short(video.title)}” mà bạn vừa nói chuyện."))
    return items[:MAX_FOLLOW_UPS]


# Kinds the agent may add to today's tasks when the learner asks (fixed wording; a video one needs an own video).
AGENT_ADDABLE_KINDS = (PlanItemKind.REVIEW, PlanItemKind.MY_WORDS, PlanItemKind.CONVERSATION,
                       PlanItemKind.VIDEO_PRACTICE)


def compose_added_item(kind: PlanItemKind, *, reviews_ready: int, saved_words: int,
                       video: PlanVideo | None) -> PlanItemDraft | None:
    """The one item the learner asked the agent to add, or None when there is nothing for it to point at."""
    if kind == PlanItemKind.REVIEW and reviews_ready > 0:
        return PlanItemDraft(kind=kind, minutes=min(10, max(2, math.ceil(reviews_ready / 2))), item_count=reviews_ready,
                             reason=f"Bạn nhờ mình thêm: ôn {reviews_ready} mục đã đến hạn.")
    if kind == PlanItemKind.MY_WORDS and saved_words > 0:
        return PlanItemDraft(kind=kind, minutes=3, item_count=saved_words,
                             reason=f"Bạn nhờ mình thêm: luyện {saved_words} từ đã lưu.")
    if kind == PlanItemKind.CONVERSATION:
        if video is None:
            return PlanItemDraft(kind=kind, minutes=5, companion_entry="home",
                                 reason="Bạn nhờ mình thêm: nói chuyện với mình về chủ đề bạn chọn.")
        return PlanItemDraft(kind=kind, minutes=5, companion_entry="video", library_item_id=video.library_item_id,
                             video_title=video.title,
                             reason=f"Bạn nhờ mình thêm: nói chuyện về video “{_short(video.title)}”.")
    if kind == PlanItemKind.VIDEO_PRACTICE and video is not None:
        return PlanItemDraft(kind=kind, minutes=5, library_item_id=video.library_item_id, video_title=video.title,
                             reason=f"Bạn nhờ mình thêm: luyện video “{_short(video.title)}”.")
    return None


def template_intro(signals: PlanSignals) -> str:
    return NEW_LEARNER_INTRO if signals.latest_video is None else TEMPLATE_INTRO


# --- Model-written text: accepted only when it is safe to show -------------------------

_GRADING = re.compile(r"\b(score|grade|points?|mastery|mastered)\b|\bđiểm\b|thành thạo|\d+\s*/\s*10",
                      re.IGNORECASE)
_LINK = re.compile(r"https?://|www\.|<[^>]+>|```")


def acceptable_text(text: str, *, max_chars: int) -> bool:
    """Plan text may encourage, never claim grading or progress, and carry no links or markup."""
    clean = " ".join(text.split())
    return 0 < len(clean) <= max_chars and not _GRADING.search(clean) and not _LINK.search(clean)


def with_reasons(items: list[PlanItemDraft], reasons: dict[int, str]) -> list[PlanItemDraft]:
    """Replace reasons by position; any position without an acceptable text keeps its template."""
    return [replace(item, reason=" ".join(reasons[index].split()))
            if index in reasons and acceptable_text(reasons[index], max_chars=MAX_REASON_CHARS) else item
            for index, item in enumerate(items)]


def _short(title: str, limit: int = 60) -> str:
    title = " ".join(title.split())
    return title if len(title) <= limit else title[: limit - 1] + "…"
