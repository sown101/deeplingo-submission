"""The agent chooses the words to practise (PRD FR-3.1).

From the words that are due for review it takes those of one topic so practice stays coherent: at most
twelve, most overdue first. A topic is one of the learner's notebooks; due words in no notebook are grouped
for the moment by the video they came from. The learner may change the topic to another of their own
notebooks; they never pick words one by one.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from app.modules.learning.application.learned_items import LearnedItem
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.domain.companion import MAX_ITEMS

logger = logging.getLogger(__name__)
GENERAL_TOPIC = "Words you are reviewing today"
_DUE_READ = 500
_MAX_NOTEBOOKS = 50


@dataclass(frozen=True)
class FocusChoice:
    title: str
    topic_id: UUID | None
    items: list[LearnedItem]


class FocusWordChooser:
    def __init__(self, *, due, groups, group_items, targets, catalog, video_topics=None):
        self.due, self.groups, self.group_items = due, groups, group_items
        self.targets, self.catalog = targets, catalog
        # Best effort: the title of the video a word was met in, to group words that are in no notebook.
        self.video_topics = video_topics

    def choose(self, user_id: UUID, *, language_code: str, support_language_code: str,
               topic_id: UUID | None = None) -> FocusChoice | None:
        rows = [row for row in self.targets.list_for_user(user_id, language_code=language_code)
                if row.get("status") in {"active", "backlog"}]
        concept_of = {str(row["id"]): str(row["concept_id"]) for row in rows}
        saved = set(concept_of.values())
        # Due order is kept: the most overdue word first.
        due_ids = self.due.due_concept_ids(user_id, language_code=language_code, limit=_DUE_READ)
        due = [value for value in dict.fromkeys(due_ids) if value in saved]
        notebooks = {str(group["id"]): group for group in
                     self.groups.list_for_user(user_id, language_code=language_code)[:_MAX_NOTEBOOKS]}
        if topic_id is not None and str(topic_id) not in notebooks:
            raise SpeakingPracticeError("not_found", "companion_topic_not_found", "That topic was not found.")
        if not due:
            if topic_id is not None:
                return FocusChoice(title=str(notebooks[str(topic_id)].get("name") or GENERAL_TOPIC),
                                   topic_id=topic_id, items=[])
            return None
        members = {group_id: {concept_of[str(saved_id)] for saved_id in self.group_items.saved_ids(UUID(group_id))
                              if str(saved_id) in concept_of} for group_id in notebooks}
        due_in = {group_id: [value for value in due if value in concept_ids]
                  for group_id, concept_ids in members.items()}
        chosen = str(topic_id) if topic_id is not None else None
        title = None
        if chosen is None and topic_id is None:
            candidates = {group_id: (str(notebooks[group_id].get("name") or GENERAL_TOPIC), words)
                          for group_id, words in due_in.items() if words}
            assigned = set().union(*members.values()) if members else set()
            for name, words in self._by_video(user_id, [value for value in due if value not in assigned]).items():
                candidates[f"video:{name}"] = (f"Words from “{name}”", words)
            best = max(candidates, key=lambda key: (len(candidates[key][1]), candidates[key][0]), default=None)
            if best is not None:
                title, words = candidates[best]
                chosen = best if best in notebooks else None
        if title is None:
            title = str(notebooks[chosen].get("name") or GENERAL_TOPIC) if chosen else GENERAL_TOPIC
            words = (due_in[chosen] if chosen else due)
        words = words[:MAX_ITEMS]
        items = self.catalog.select(user_id, [UUID(value) for value in words], language_code=language_code,
                                    support_language_code=support_language_code) if words else []
        return FocusChoice(title=title, topic_id=UUID(chosen) if chosen else None, items=items)

    def _by_video(self, user_id: UUID, concept_ids: list[str]) -> dict[str, list[str]]:
        if self.video_topics is None or not concept_ids:
            return {}
        try:
            titles = self.video_topics.titles_for(user_id, concept_ids)
        except Exception as exc:
            logger.warning("video topics unavailable error=%s", type(exc).__name__)
            return {}
        grouped: dict[str, list[str]] = {}
        for value in concept_ids:
            title = " ".join(str(titles.get(value) or "").split())[:80]
            if title:
                grouped.setdefault(title, []).append(value)
        return grouped
