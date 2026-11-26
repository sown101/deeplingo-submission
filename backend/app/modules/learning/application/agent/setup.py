"""The server-built context of one conversation, shared by the voice and the text channel.

Languages from the learner's profile; then one of three modes: a study region (or the part of a video being
watched), a topic (the words due in one notebook, or recent words), or a roleplay situation. Every selector the
client sends is rechecked against the learner's own Library, transcript, region and notebooks. No model call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.kernel.region_ids import region_id as make_region_id
from app.modules.learning.application.agent.ports import (
    CompanionTicket,
    ConversationFollowUps,
    DueConceptReader,
    StudyRegionReader,
    WordLookup,
)
from app.modules.learning.application.learned_items import LearnedItem, LearnedItemCatalog
from app.modules.learning.application.selected_targets import SelectedTargetCatalog
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.domain.companion import (
    MAX_EXCERPT_CHARS,
    MAX_ITEMS,
    CompanionEntry,
    CompanionItem,
    CompanionMessage,
    RegionLine,
    clip_message,
    render_region_excerpt,
)
from app.modules.learning.domain.roleplay import SCENARIOS, find_scenario
from app.modules.learning.domain.speaking import normalize_for_matching

logger = logging.getLogger(__name__)

EXCERPT_SEGMENTS = 6
UNAVAILABLE = ("unavailable", "companion_unavailable", "The companion is temporarily unavailable.")
EXPIRED = ("invalid_input", "companion_session_invalid", "This conversation has ended. Start a new one.")


@dataclass(frozen=True)
class PreparedConversation:
    """A new conversation's context before any model call."""

    ticket: CompanionTicket
    # The words to practise were chosen by the agent (due words of one topic), not taken from a video.
    focused: bool = False


@dataclass(frozen=True)
class _Context:
    topic: str
    excerpt: str | None
    items: list[CompanionItem]
    lines: tuple[RegionLine, ...] = ()
    region_id: str | None = None


class ConversationSetup:
    def __init__(self, *, preferences, catalog: LearnedItemCatalog, library, videos, transcripts, segments,
                 due: DueConceptReader | None = None, regions: StudyRegionReader | None = None,
                 target_catalog: SelectedTargetCatalog | None = None, focus=None,
                 word_lookup: WordLookup | None = None, follow_ups: ConversationFollowUps | None = None, **_channel):
        self.preferences = preferences
        self.catalog = catalog
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments
        self.due = due
        self.regions = regions
        self.target_catalog = target_catalog
        self.focus = focus
        self.word_lookup = word_lookup
        self.follow_ups = follow_ups

    def scenarios(self, user) -> list[dict]:
        _, support = self._languages(user)
        return [scenario.view(support) for scenario in SCENARIOS]

    def prepare(self, user, entry: CompanionEntry, library_item_id: UUID | None,
                segment_id: UUID | None = None, topic_id: UUID | None = None,
                scenario_id: str | None = None, swap_roles: bool = False) -> PreparedConversation:
        """Server-built context for a new conversation: languages, mode, topic and offered items."""
        language, support = self._languages(user)
        if scenario_id is not None:
            scenario = find_scenario(scenario_id)
            if scenario is None:
                raise SpeakingPracticeError("invalid_input", "companion_scenario_invalid", "Choose an available situation.")
            context = _Context(topic=scenario.title[0], excerpt=None, items=[])
            if entry == CompanionEntry.VIDEO:
                context = self._context(user, entry, library_item_id, language, support, segment_id=segment_id)
            elif self.focus is not None:
                choice = self.focus.choose(user.id, language_code=language, support_language_code=support, topic_id=topic_id)
                if choice is not None and (topic_id is None or choice.topic_id == topic_id):
                    context = _Context(topic=scenario.title[0], excerpt=None, items=[CompanionItem(
                        item_id=word.concept_id, text=word.text, meaning=word.meaning, forms=word.forms,
                        practiced=False) for word in choice.items])
            ticket = CompanionTicket(user_id=user.id, language_code=language, support_language_code=support,
                entry=entry, library_item_id=library_item_id if entry == CompanionEntry.VIDEO else None,
                topic=scenario.title[0], items=tuple(context.items), excerpt=context.excerpt,
                region_lines=context.lines, scenario_id=scenario.id, swap_roles=swap_roles,
                region_id=context.region_id)
            return PreparedConversation(ticket=ticket, focused=bool(context.items))
        choice = None
        if entry == CompanionEntry.HOME and library_item_id is None and segment_id is None and self.focus is not None:
            choice = self.focus.choose(user.id, language_code=language, support_language_code=support, topic_id=topic_id)
            if choice is not None and choice.items:
                return self.prepare_selected(user, entry, None, [UUID(item.concept_id) for item in choice.items],
                                             topic=choice.title)
        if choice is not None:
            context = _Context(topic=choice.title, excerpt=None, items=[])
        else:
            context = self._context(user, entry, library_item_id, language, support, segment_id=segment_id)
        ticket = CompanionTicket(
            user_id=user.id, language_code=language, support_language_code=support, entry=entry,
            library_item_id=library_item_id if entry == CompanionEntry.VIDEO else None,
            topic=context.topic, items=tuple(context.items), excerpt=context.excerpt, region_lines=context.lines,
            region_id=context.region_id,
        )
        return PreparedConversation(ticket=ticket)

    def prepare_selected(self, user, entry: CompanionEntry, library_item_id: UUID | None,
                         concept_ids: list[UUID], segment_id: UUID | None = None,
                         topic: str | None = None) -> PreparedConversation:
        """L2: explicit owned targets, including backlog; no activation or provider call."""
        language, support = self._languages(user)
        if self.target_catalog is None:
            raise SpeakingPracticeError(*UNAVAILABLE)
        selected = self.target_catalog.select(user.id, concept_ids, language_code=language,
                                              support_language_code=support)
        context = self._context(user, entry, library_item_id, language, support, selected_items=selected,
                                segment_id=segment_id)
        ticket = CompanionTicket(user_id=user.id, language_code=language, support_language_code=support,
                                 entry=entry, library_item_id=library_item_id if entry == CompanionEntry.VIDEO else None,
                                 topic=topic or context.topic, items=tuple(context.items),
                                 excerpt=context.excerpt, region_lines=context.lines, region_id=context.region_id)
        return PreparedConversation(ticket=ticket, focused=True)

    def end_conversation(self, user, prepared: PreparedConversation, history: list[CompanionMessage],
                         day: date | None) -> list:
        """A voice conversation ended: its follow-ups for today's plan."""
        if prepared.ticket.user_id != user.id:
            raise SpeakingPracticeError(*EXPIRED)
        return self.follow_ups_after(user, prepared.ticket, history, day)

    def follow_ups_after(self, user, ticket: CompanionTicket, history: list[CompanionMessage],
                         day: date | None) -> list:
        """Only after the learner spoke; any failure means none."""
        if self.follow_ups is None or day is None or not any(message.role == "learner" for message in history):
            return []
        try:
            return self.follow_ups.after_conversation(user, day, library_item_id=ticket.library_item_id)
        except Exception as exc:
            logger.warning("companion follow-ups unavailable error=%s", type(exc).__name__)
            return []

    # --- Context -------------------------------------------------------------------------------

    def _context(self, user, entry: CompanionEntry, library_item_id: UUID | None, language: str,
                 support: str, *, selected_items: list[LearnedItem] | None = None,
                 segment_id: UUID | None = None) -> _Context:
        if entry == CompanionEntry.VIDEO:
            if library_item_id is None:
                raise SpeakingPracticeError("invalid_input", "companion_video_required", "Choose a video first.")
            video = self._owned_video(user, library_item_id)
            watching, watching_ids = self._watching(video, segment_id) if segment_id else (None, set())
            # M1 S7b: video conversations never read ConceptMastery. With a study part, readiness is the part's.
            region = self._region(user, library_item_id)
            has_part = region is not None and bool(region.lines)
            if video.original_language_code != language or (not has_part and video.learning_status != "ready"):
                raise SpeakingPracticeError("conflict", "companion_video_not_ready",
                                            "This video is not ready for conversation yet.")
            if region is not None:
                # M1 S3: talk about the learner's study region; items come from the region first, else the video.
                excerpt, lines = render_region_excerpt(region)
                if lines:
                    segment_ids = {UUID(line.segment_id) for line in lines}
                    learned = selected_items if selected_items is not None else self.catalog.for_learner(
                        user.id, language_code=language, support_language_code=support, owned_videos=[video],
                        segment_ids=segment_ids,
                    ) or self.catalog.for_learner(
                        user.id, language_code=language, support_language_code=support, owned_videos=[video],
                    )
                    return _Context(video.title, _with_watching(watching, excerpt),
                                    self._offered(learned, preserve_senses=selected_items is not None), lines,
                                    make_region_id(region.lines[0].segment_id, region.lines[-1].segment_id))
            learned = selected_items
            if learned is None and watching_ids:
                learned = self.catalog.for_learner(
                    user.id, language_code=language, support_language_code=support, owned_videos=[video],
                    segment_ids=watching_ids) or None
            if learned is None:
                learned = self.catalog.for_learner(
                    user.id, language_code=language, support_language_code=support, owned_videos=[video])
            return _Context(video.title, _with_watching(watching, self._excerpt(video)),
                            self._offered(learned, preserve_senses=selected_items is not None))
        if library_item_id is not None or segment_id is not None:
            raise SpeakingPracticeError("invalid_input", "companion_selector_unexpected",
                                        "A video can only be chosen for a video conversation.")
        if selected_items is not None:
            return _Context("Words you chose to practise", None, self._offered(selected_items, preserve_senses=True))
        learned = self.catalog.for_learner(user.id, language_code=language, support_language_code=support)
        if entry == CompanionEntry.REVIEW:
            due = set(self.due.due_concept_ids(user.id, language_code=language, limit=50)) if self.due is not None else set()
            learned = [item for item in learned if item.concept_id in due]
            topic = "Words you are reviewing today"
        else:
            topic = "Everyday life and the videos you watched recently"
        return _Context(topic, None, self._offered(learned))

    def _offered(self, learned: list[LearnedItem], *, preserve_senses: bool = False) -> list[CompanionItem]:
        # One item per surface text: two senses of the same word would only confuse a beginner.
        unique: dict[str, LearnedItem] = {}
        for item in learned:
            unique.setdefault(item.concept_id if preserve_senses else normalize_for_matching(item.text), item)
        items = [CompanionItem(item_id=item.concept_id, text=item.text,
                               meaning=(item.meaning or None) and clip_message(item.meaning)[:120],
                               forms=item.forms, practiced=item.source == "practiced")
                 for item in list(unique.values())[:MAX_ITEMS]]
        if not items:
            raise SpeakingPracticeError("conflict", "companion_no_items",
                                        "Watch and prepare a video first, then talk about it.")
        return items

    def _owned_video(self, user, library_item_id: UUID):
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user.id)
        video = self.videos.get_by_id(association.video_id) if association is not None else None
        if video is None:
            raise SpeakingPracticeError("not_found", "companion_video_not_found", "Video not found.")
        return video

    def recheck_owner(self, user, library_item_id: UUID) -> None:
        """Every turn: the video must still be in this learner's Library (one read)."""
        if self.library.get_for_user(library_item_id=library_item_id, user_id=user.id) is None:
            raise SpeakingPracticeError("not_found", "companion_video_not_found", "Video not found.")

    def _region(self, user, library_item_id: UUID):
        """The learner's study region of this owned video, or None when no region is chosen."""
        if self.regions is None:
            return None
        try:
            return self.regions.for_learner(user.id, library_item_id)
        except Exception as exc:
            # M1 S7b: a part that cannot be read is not "no part": never talk about another part instead.
            logger.warning("companion study region unavailable error=%s", type(exc).__name__)
            raise SpeakingPracticeError("unavailable", "companion_region_unavailable",
                                        "Your study part could not be loaded. Try again in a moment.") from exc

    def _watching(self, video, segment_id: UUID) -> tuple[str, set[UUID]]:
        """The part being watched with its neighbours. The segment must belong to the original transcript
        of this learner's own video: Library item, video, transcript and segment are checked as a chain."""
        transcript = next((row for row in self.transcripts.list_for_video(video.id)
                           if row.is_original and row.language_code == video.original_language_code), None)
        current = self.segments.get_by_id(segment_id) if transcript is not None and transcript.id else None
        if current is None or current.transcript_id != transcript.id:
            raise SpeakingPracticeError("not_found", "companion_segment_not_found", "That part of the video was not found.")
        neighbours = [self.segments.get_neighbor(transcript_id=transcript.id, sequence_number=current.sequence_number,
                                                 offset=offset) for offset in (-1, 1)]
        seconds = max(0, current.start_ms) // 1000
        pieces = [f"Playing now ({seconds // 60:02d}:{seconds % 60:02d}): {_one_line(current.text)}"]
        if neighbours[0] is not None:
            pieces.insert(0, _one_line(neighbours[0].text))
        if neighbours[1] is not None:
            pieces.append(_one_line(neighbours[1].text))
        ids = {part.id for part in (current, *neighbours) if part is not None and part.id is not None}
        return " ".join(pieces), ids

    def _excerpt(self, video) -> str | None:
        transcript = next((row for row in self.transcripts.list_for_video(video.id)
                           if row.is_original and row.language_code == video.original_language_code), None)
        if transcript is None or transcript.id is None:
            return None
        segments = self.segments.list_head_for_transcript(transcript.id, limit=EXCERPT_SEGMENTS)
        text = " ".join(" ".join(segment.text for segment in segments).split())
        return text[:MAX_EXCERPT_CHARS] or None

    def _languages(self, user) -> tuple[str, str]:
        profile = self.preferences.get_profile_for_user(user.id)
        if profile is None or not profile.language_code:
            raise SpeakingPracticeError("conflict", "language_profile_required", "Choose your learning language first.")
        return profile.language_code, profile.support_language_code or "vi"


def _one_line(text: str) -> str:
    return " ".join(text.split())[:300]


def _with_watching(watching: str | None, excerpt: str | None) -> str | None:
    """What the learner is watching right now comes first; the rest of the excerpt follows."""
    if not watching:
        return excerpt
    return f"{watching}\n{excerpt}" if excerpt else watching
