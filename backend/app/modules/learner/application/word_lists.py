"""Named word lists and bulk import (L1b).

A list groups the learner's targets ("Travel", "IELTS Part 2"). A learner pastes words, one per line;
the server finds each word in the dictionary:

- one meaning        -> it becomes a target at once (priority below an explicit save, in the backlog);
- several meanings   -> the line waits, with the meanings the server found, until the learner picks one;
- no dictionary entry -> the line waits as unresolved and is never turned into a word on its own.

The learner never sends a Concept or a meaning text: choosing a meaning means naming one of the stored
candidates. Lists are private. Imports never ask the out-of-level question; the report counts those
words instead.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.ports import (
    ConceptListReader,
    GroupItemStore,
    GroupStore,
    HeadwordResolver,
    ImportRowStore,
    LanguagePreferenceStore,
    SenseConceptResolver,
    TargetStore,
)
from app.modules.learner.application.word_targets import WordTargetsService
from app.modules.learner.domain.levels import is_above_level
from app.modules.learner.domain.word_lists import (
    MAX_CANDIDATES,
    MAX_GROUPS_PER_LEARNER,
    MAX_LIST_ROWS,
    SenseCandidate,
    parse_import_batch,
    validate_list_name,
)
from app.modules.learner.domain.word_targets import PRIORITY_IMPORT

logger = logging.getLogger(__name__)


class WordListError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class CandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: UUID
    sense_id: str
    headword: str
    text: str
    part_of_speech: str | None = None


class WaitingLineView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    text: str
    gloss: str | None
    resolution: Literal["ambiguous", "unresolved"]
    candidates: list[CandidateView] = Field(default_factory=list)


class ListWordView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: UUID
    text: str
    gloss: str | None
    status: str
    rung: int
    level_label: str | None
    above_level: bool
    reading: str | None = None
    traditional: str | None = None
    note: str | None = None
    favorite: bool = False


class ListSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    language_code: str
    name: str
    description: str | None
    word_count: int
    waiting_count: int
    created_at: datetime | None = None


class ListDetailView(ListSummaryView):
    words: list[ListWordView] = Field(default_factory=list)
    waiting: list[WaitingLineView] = Field(default_factory=list)


class ImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: int = 0
    ambiguous: int = 0
    unresolved: int = 0
    already_in_list: int = 0
    duplicates: int = 0
    too_long: int = 0
    over_limit: int = 0
    above_level: int = 0
    list_full: bool = False


class WordListService:
    def __init__(self, *, groups: GroupStore, items: GroupItemStore, rows: ImportRowStore, targets_store: TargetStore,
                 targets: WordTargetsService, resolver: HeadwordResolver, senses: SenseConceptResolver,
                 concepts: ConceptListReader, preferences: LanguagePreferenceStore, dictionary=None):
        self.dictionary = dictionary
        self.groups = groups
        self.items = items
        self.rows = rows
        self.targets_store = targets_store
        self.targets = targets
        self.resolver = resolver
        self.senses = senses
        self.concepts = concepts
        self.preferences = preferences

    # --- Lists ---------------------------------------------------------------------------------

    def create(self, user: CurrentUser, *, language_code: str, name: str, description: str | None = None) -> ListSummaryView:
        language = language_code.strip().casefold()
        if self.preferences.get_by_language_for_user(user_id=user.id, language_code=language) is None:
            raise WordListError("You are not learning this language.", status_code=422, code="language_not_learned")
        try:
            cleaned = validate_list_name(name)
        except ValueError as exc:
            raise WordListError(str(exc), status_code=422, code="invalid_list_name") from exc
        existing = self.groups.list_for_user(user.id)
        if len(existing) >= MAX_GROUPS_PER_LEARNER:
            raise WordListError("You have reached the limit of lists.", status_code=409, code="too_many_lists")
        if any(row["language_code"] == language and row["name"].casefold() == cleaned.casefold() for row in existing):
            raise WordListError("You already have a list with this name.", status_code=409, code="list_name_taken")
        row = self.groups.create(user.id, language_code=language, name=cleaned,
                                 description=(description or "").strip()[:300] or None)
        return self._summary(row, words=0, waiting=0)

    def list(self, user: CurrentUser, language_code: str | None = None) -> list[ListSummaryView]:
        language = language_code.strip().casefold() if language_code else None
        rows = self.groups.list_for_user(user.id, language_code=language)
        ids = [UUID(str(row["id"])) for row in rows]
        words, waiting = self.items.counts(ids), self.rows.counts(ids)
        return [self._summary(row, words=words.get(UUID(str(row["id"])), 0), waiting=waiting.get(UUID(str(row["id"])), 0))
                for row in rows]

    def detail(self, user: CurrentUser, group_id: UUID) -> ListDetailView:
        group = self._owned(user, group_id)
        saved_ids = set(self.items.saved_ids(group_id))
        targets = [row for row in self.targets_store.list_for_user(user.id, language_code=group["language_code"])
                   if UUID(str(row["id"])) in saved_ids]
        concept_ids = [UUID(str(row["concept_id"])) for row in targets]
        concepts = {item.id: item for item in (self.concepts.list_by_ids(concept_ids) if concept_ids else [])}
        declared = self.targets.settings(user.id, group["language_code"]).declared_level
        readings = (self.dictionary.readings_for(group["language_code"], [item.canonical_text for item in concepts.values()])
                    if self.dictionary is not None else {})
        words = []
        for row in targets:
            concept = concepts.get(UUID(str(row["concept_id"])))
            if concept is None:
                continue
            gloss = (concept.metadata or {}).get("sense_gloss")
            words.append(ListWordView(
                concept_id=concept.id, text=concept.canonical_text, gloss=gloss if isinstance(gloss, str) else None,
                status=row.get("status") or "active", rung=int(row.get("rung") or 0), level_label=row.get("level_label"),
                above_level=is_above_level(concept.language_code, row.get("level_label"), declared),
                reading=readings.get(concept.canonical_text, (None, None))[0],
                traditional=readings.get(concept.canonical_text, (None, None))[1],
                note=row.get("note"), favorite=bool(row.get("favorite"))))
        waiting = [self._waiting(row) for row in self.rows.list(group_id)]
        summary = self._summary(group, words=len(words), waiting=len(waiting))
        return ListDetailView(**summary.model_dump(), words=words, waiting=waiting)

    def delete(self, user: CurrentUser, group_id: UUID) -> None:
        """Deletes the list only: the learner's words stay."""
        self._owned(user, group_id)
        self.groups.delete(user.id, group_id)

    # --- Words in a list -----------------------------------------------------------------------

    def add_word(self, user: CurrentUser, group_id: UUID, concept_id: UUID) -> None:
        group = self._owned(user, group_id)
        target = self.targets_store.get(user.id, concept_id)
        if target is None or target.get("language_code") not in (None, group["language_code"]):
            raise WordListError("Word not found.", status_code=404, code="word_not_found")
        self._check_room(group_id)
        self.items.add(group_id, UUID(str(target["id"])))

    def add_from_set(self, user: CurrentUser, group_id: UUID, entry_ids: list[UUID]) -> ImportReport:
        """Words picked from a ready-made set: each entry's first meaning, in the list's language."""
        group = self._owned(user, group_id)
        language = group["language_code"]
        report = ImportReport()
        room = MAX_LIST_ROWS - self._size(group_id)
        report.list_full = room < len(entry_ids)
        declared = self.targets.settings(user.id, language).declared_level
        in_list = set(self.items.saved_ids(group_id))
        for entry_id in entry_ids[:max(room, 0)]:
            found = self.dictionary.first_sense(entry_id) if self.dictionary is not None else None
            if found is None or found["language_code"] != language:
                report.unresolved += 1
                continue
            self._import_single(user, group_id, language, SenseCandidate(
                entry_id=entry_id, sense_id=found["sense"]["sense_id"], headword=found["headword"],
                text=found["sense"]["text"]), declared, in_list, report)
        return report

    def remove_word(self, user: CurrentUser, group_id: UUID, concept_id: UUID) -> None:
        self._owned(user, group_id)
        target = self.targets_store.get(user.id, concept_id)
        if target is None or not self.items.remove(group_id, UUID(str(target["id"]))):
            raise WordListError("Word not found in this list.", status_code=404, code="word_not_in_list")

    # --- Import --------------------------------------------------------------------------------

    def import_text(self, user: CurrentUser, group_id: UUID, text: str) -> ImportReport:
        group = self._owned(user, group_id)
        language = group["language_code"]
        parsed = parse_import_batch(text)
        report = ImportReport(duplicates=parsed.duplicates, too_long=parsed.too_long, over_limit=parsed.over_limit)
        room = MAX_LIST_ROWS - self._size(group_id)
        lines = parsed.lines[:max(room, 0)]
        report.list_full = room < len(parsed.lines)
        if not lines:
            return report
        waiting_words = self.rows.raw_words(group_id)
        lines = [line for line in lines if line.word.casefold() not in waiting_words]
        candidates = self.resolver.candidates_for(language, [line.word for line in lines])
        declared = self.targets.settings(user.id, language).declared_level
        in_list = set(self.items.saved_ids(group_id))
        position = self.rows.next_position(group_id)
        for line in lines:
            found = candidates.get(line.word, [])[:MAX_CANDIDATES]
            if len(found) == 1:
                self._import_single(user, group_id, language, found[0], declared, in_list, report)
                continue
            resolution = "ambiguous" if len(found) > 1 else "unresolved"
            self.rows.add(group_id, user.id, position=position, raw_text=line.word, user_gloss=line.gloss,
                          resolution=resolution, candidates=[item.as_json() for item in found])
            position += 1
            if resolution == "ambiguous":
                report.ambiguous += 1
            else:
                report.unresolved += 1
        return report

    def choose_meaning(self, user: CurrentUser, group_id: UUID, row_id: UUID, *, entry_id: UUID, sense_id: str) -> ListWordView:
        """The learner picks one of the meanings the server stored for a waiting line."""
        group = self._owned(user, group_id)
        row = self.rows.get(group_id, row_id)
        if row is None:
            raise WordListError("Line not found.", status_code=404, code="line_not_found")
        stored = [SenseCandidate.from_json(item) for item in row.get("candidates") or []]
        if not any(item.entry_id == entry_id and item.sense_id == sense_id for item in stored):
            raise WordListError("That meaning is not offered for this word.", status_code=422, code="sense_not_offered")
        try:
            concept = self.senses.from_dictionary(language_code=group["language_code"], entry_id=entry_id, sense_id=sense_id)
        except ValueError as exc:
            raise WordListError(str(exc), status_code=getattr(exc, "status_code", 422),
                                code=getattr(exc, "code", "sense_not_offered")) from exc
        saved = self.targets.register(user, concept, save_source="import", explicit=True, priority=PRIORITY_IMPORT,
                                      acknowledge_above_level=True)
        self.items.add(group_id, UUID(str(saved["id"])))
        self.rows.delete(group_id, row_id)
        declared = self.targets.settings(user.id, group["language_code"]).declared_level
        gloss = (concept.metadata or {}).get("sense_gloss")
        return ListWordView(
            concept_id=concept.id, text=concept.canonical_text, gloss=gloss if isinstance(gloss, str) else None,
            status=saved.get("status") or "backlog", rung=int(saved.get("rung") or 0), level_label=saved.get("level_label"),
            above_level=is_above_level(concept.language_code, saved.get("level_label"), declared))

    def dismiss_line(self, user: CurrentUser, group_id: UUID, row_id: UUID) -> None:
        self._owned(user, group_id)
        if not self.rows.delete(group_id, row_id):
            raise WordListError("Line not found.", status_code=404, code="line_not_found")

    # --- Internals -----------------------------------------------------------------------------

    def _import_single(self, user, group_id, language, candidate: SenseCandidate, declared, in_list: set, report) -> None:
        try:
            concept = self.senses.from_dictionary(language_code=language, entry_id=candidate.entry_id,
                                                  sense_id=candidate.sense_id)
            saved = self.targets.register(user, concept, save_source="import", explicit=True, priority=PRIORITY_IMPORT,
                                          acknowledge_above_level=True)
        except ValueError:
            logger.warning("import could not turn a unique meaning into a word", exc_info=True)
            report.unresolved += 1
            return
        saved_id = UUID(str(saved["id"]))
        if saved_id in in_list:
            report.already_in_list += 1
            return
        self.items.add(group_id, saved_id)
        in_list.add(saved_id)
        report.matched += 1
        if is_above_level(concept.language_code, saved.get("level_label"), declared):
            report.above_level += 1

    def _owned(self, user: CurrentUser, group_id: UUID) -> dict:
        group = self.groups.get(user.id, group_id)
        if group is None:
            # The same answer for another learner's list and for a missing one.
            raise WordListError("List not found.", status_code=404, code="list_not_found")
        return group

    def _size(self, group_id: UUID) -> int:
        return self.items.counts([group_id]).get(group_id, 0) + self.rows.counts([group_id]).get(group_id, 0)

    def _check_room(self, group_id: UUID) -> None:
        if self._size(group_id) >= MAX_LIST_ROWS:
            raise WordListError("This list is full.", status_code=409, code="list_full")

    @staticmethod
    def _summary(row: dict, *, words: int, waiting: int) -> ListSummaryView:
        return ListSummaryView(
            id=UUID(str(row["id"])), language_code=row["language_code"], name=row["name"],
            description=row.get("description"), word_count=words, waiting_count=waiting,
            created_at=row.get("created_at"))

    @staticmethod
    def _waiting(row: dict) -> WaitingLineView:
        return WaitingLineView(
            id=UUID(str(row["id"])), text=row["raw_text"], gloss=row.get("user_gloss"), resolution=row["resolution"],
            candidates=[CandidateView(**{**item, "entry_id": UUID(str(item["entry_id"]))})
                        for item in row.get("candidates") or []])
