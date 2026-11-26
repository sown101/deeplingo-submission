"""Which of the learner's saved words a conversation may be checked against (PRD FR-3.5).

A cheap whole-form match over the learner's own turns picks the few saved words that were really
said; only those reach the model, which still checks the exact meaning. Prior support (what the
companion said or showed before a turn) is derived here from the server's own record.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from app.modules.learning.application.learned_items import LearnedItem
from app.modules.learning.application.session_events import LearnerTurn, contains_form
from app.modules.learning.domain.companion import MAX_ITEMS


def saved_word_targets(saved: Iterable[LearnedItem], turns: Sequence[LearnerTurn], language_code: str, *,
                       selected: Sequence[LearnedItem] = (), limit: int = MAX_ITEMS) -> list[LearnedItem]:
    """Words the learner said first, in the order first said; then selected words that were not said.

    Only a word that was said can become evidence, so selected words must not take the place of a
    saved word the learner really used (Codex review, 2026-11-05). Selected words count as said
    on their forms alone; other saved words also need a meaning.
    """
    selected = list(selected)
    candidates = [*selected, *(word for word in saved if word.meaning)]
    chosen: list[LearnedItem] = []
    seen: set[str] = set()
    for turn in turns:
        for word in candidates:
            if len(chosen) >= limit:
                return chosen
            if word.concept_id in seen:
                continue
            if any(contains_form(turn.text, form, language_code) for form in word.forms):
                chosen.append(word)
                seen.add(word.concept_id)
    for word in selected:
        if len(chosen) >= limit:
            break
        if word.concept_id not in seen:
            chosen.append(word)
            seen.add(word.concept_id)
    return chosen


def turns_with_server_support(turns: Sequence[LearnerTurn], examples: Sequence[str],
                              targets: Sequence[LearnedItem], language_code: str) -> list[LearnerTurn]:
    """Mark a target as assisted in every turn that followed the companion saying or showing it."""
    result = []
    for turn in turns:
        seen = examples[:turn.examples_seen]
        prior = [UUID(word.concept_id) for word in targets
                 if any(contains_form(example, form, language_code) for example in seen for form in word.forms)]
        result.append(turn.model_copy(update={"assisted_ids": list(dict.fromkeys([*turn.assisted_ids, *prior]))}))
    return result
