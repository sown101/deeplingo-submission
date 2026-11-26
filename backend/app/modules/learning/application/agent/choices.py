"""What the agent offers when the learner opens it without a topic: a few short choices built from their context.

The agent greets, asks what the learner wants and shows these as tappable options; it never picks a topic on its
own. The server builds them (no model call). The learner may also just say what they want. Labels are the client's
(per language); the server only names the choice and, for the words, how many are due.
"""
from __future__ import annotations

from app.modules.learning.application.agent.context import LearnerContext
from app.modules.learning.domain.companion import CompanionEntry

# Learning-log kinds that mean the learner worked on a part of a video.
VIDEO_KINDS = frozenset({"dictation", "shadowing", "region_question"})
CHOICE_IDS = ("video", "words", "roleplay", "free")


def starts_open(entry, *, library_item_id=None, segment_id=None, topic_id=None, scenario_id=None) -> bool:
    """The learner opened the agent from Home without choosing a video, a notebook topic or a situation."""
    return entry == CompanionEntry.HOME and not (library_item_id or segment_id or topic_id or scenario_id)


def opening_choices(*, words: int, context: LearnerContext | None) -> list[dict]:
    """The options for this learner now: a video part they studied, today's due words, a situation, or free talk."""
    choices: list[dict] = []
    if context is not None and any(row.get("kind") in VIDEO_KINDS for row in context.recent):
        choices.append({"id": "video"})
    if words:
        choices.append({"id": "words", "count": words})
    choices += [{"id": "roleplay"}, {"id": "free"}]
    return choices
