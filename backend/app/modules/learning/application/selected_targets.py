"""Read-only L2 words explicitly selected from the learner's own L1 targets."""
from __future__ import annotations

from uuid import UUID

from app.modules.learning.application.learned_items import LearnedItem
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.domain.companion import MAX_ITEMS


class SelectedTargetCatalog:
    def __init__(self, *, targets, concepts, meanings, occurrences):
        self.targets, self.concepts = targets, concepts
        self.meanings, self.occurrences = meanings, occurrences

    def select(self, user_id: UUID, concept_ids: list[UUID], *, language_code: str,
               support_language_code: str) -> list[LearnedItem]:
        if not 1 <= len(concept_ids) <= MAX_ITEMS or len(set(concept_ids)) != len(concept_ids):
            raise SpeakingPracticeError("invalid_input", "companion_targets_invalid",
                                        "Choose between one and twelve different words.")
        owned = {UUID(str(row["concept_id"])) for row in self.targets.list_for_user(
            user_id, language_code=language_code) if row.get("status") in {"active", "backlog"}}
        if not set(concept_ids) <= owned:
            raise self._unavailable()
        concepts = {concept.id: concept for concept in self.concepts.list_by_ids(concept_ids)
                    if concept.language_code == language_code}
        if set(concepts) != set(concept_ids):
            raise self._unavailable()
        return self._items(user_id, concept_ids, concepts, support_language_code)

    def saved_items(self, user_id: UUID, *, language_code: str, support_language_code: str) -> list[LearnedItem]:
        """Every word the learner saved in this language, paused ones included, read-only."""
        owned = {UUID(str(row["concept_id"])) for row in self.targets.list_for_user(
            user_id, language_code=language_code) if row.get("status") in {"active", "backlog", "suspended"}}
        if not owned:
            return []
        concepts = {concept.id: concept for concept in self.concepts.list_by_ids(list(owned))
                    if concept.language_code == language_code}
        return self._items(user_id, [concept_id for concept_id in sorted(owned, key=str) if concept_id in concepts], concepts,
                           support_language_code)

    def _items(self, user_id: UUID, concept_ids: list[UUID], concepts: dict, support_language_code: str):
        senses = {}
        for concept_id, concept in concepts.items():
            data = concept.metadata or {}
            if isinstance(data.get("dictionary_sense_id"), str) and data.get("dictionary_entry_id"):
                try:
                    senses[concept_id] = (UUID(str(data["dictionary_entry_id"])), data["dictionary_sense_id"])
                except ValueError:
                    continue
        translated = self.meanings.for_senses(list(senses.values()), support_language_code=support_language_code)
        occurrences = self.occurrences.sentences_for(user_id, concept_ids,
                                                     support_language_code=support_language_code)
        items = []
        for concept_id in concept_ids:
            concept = concepts[concept_id]
            occurrence = occurrences.get(concept_id)
            meaning = translated.get(senses.get(concept_id), {}).get("meaning")
            if not meaning and occurrence is not None:
                meaning = occurrence.meaning
            forms = [concept.canonical_text]
            if occurrence is not None and occurrence.target_form not in forms:
                forms.append(occurrence.target_form)
            items.append(LearnedItem(concept_id=str(concept_id), text=concept.canonical_text,
                                     kind=getattr(concept.type, "value", str(concept.type)), meaning=meaning,
                                     source="selected", forms=tuple(forms)))
        return items

    @staticmethod
    def _unavailable():
        return SpeakingPracticeError("not_found", "companion_targets_unavailable",
                                     "Some selected words are unavailable. Choose your words again.")
