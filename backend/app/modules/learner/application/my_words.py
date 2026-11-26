"""My words: the learner's saved words.

Saving is a learner request stored in `saved_concepts`; the Concept is always resolved by
the content module from a trusted lookup, a dictionary sense or an owned occurrence. Nothing
here changes mastery, skills or review; the view only reads them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.kernel.region_ids import split_region_id
from app.modules.activity.contracts import log_activity
from app.modules.content.contracts import Concept
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.ports import ConceptListReader, LanguagePreferenceStore
from app.modules.learner.application.word_targets import TargetSummary, WordTargetsError, WordTargetsService
from app.modules.learner.domain.concept_lists import ConceptList, SavedWord, SaveSource
from app.modules.learner.domain.levels import is_above_level
from app.modules.learner.domain.word_targets import PRIORITY_EXPLICIT, TargetStatus


class MyWordsError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str, extra: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.extra = extra or {}
        super().__init__(message)


class SaveFromLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["lookup"]
    library_item_id: UUID
    segment_id: UUID
    start_codepoint: int = Field(ge=0)
    end_codepoint: int = Field(gt=0)
    sense_id: str | None = Field(default=None, max_length=80)
    acknowledge_above_level: bool = False
    region_id: str | None = Field(default=None, max_length=80)  # the study region it was looked up in


class SaveFromDictionary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["dictionary"]
    language_code: str = Field(min_length=2, max_length=16)
    entry_id: UUID
    sense_id: str = Field(min_length=1, max_length=80)
    acknowledge_above_level: bool = False


class SaveFromOccurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["occurrence"]
    library_item_id: UUID
    learning_object_id: UUID
    acknowledge_above_level: bool = False
    region_id: str | None = Field(default=None, max_length=80)  # the study region it was tapped in


SaveWordRequest = Annotated[SaveFromLookup | SaveFromDictionary | SaveFromOccurrence,
                            Field(discriminator="source")]


class MyWordView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: UUID
    language_code: str
    text: str
    kind: str
    gloss: str | None
    list: ConceptList
    saved: bool
    save_source: SaveSource | None
    added_at: datetime | None
    next_review_at: datetime | None
    # L1a: the target's lifecycle.
    status: Literal["backlog", "active", "suspended"] = "active"
    explicit: bool = True
    priority: int = 0
    level_label: str | None = None
    rung: int = 0
    above_level: bool = False
    reading: str | None = None
    traditional: str | None = None
    note: str | None = None
    favorite: bool = False


class MyWordsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    words: list[MyWordView]
    summary: TargetSummary | None = None


class WordConceptResolver(Protocol):
    def from_lookup(self, user, library_item_id: UUID, *, segment_id: UUID, start_codepoint: int,
                    end_codepoint: int, sense_id: str | None) -> Concept: ...
    def from_dictionary(self, *, language_code: str, entry_id: UUID, sense_id: str) -> Concept: ...
    def from_occurrence(self, user, library_item_id: UUID, learning_object_id: UUID) -> Concept: ...


class SavedConceptStore(Protocol):
    def list_for_user(self, user_id: UUID) -> list[dict]: ...
    def save(self, user_id: UUID, *, concept_id: UUID, save_source: str,
             source_learning_object_id: UUID | None = None) -> dict: ...
    def remove(self, user_id: UUID, *, concept_id: UUID) -> bool: ...


class NextReviewReader(Protocol):
    def next_due_by_concept(self, *, user_id: UUID, concept_ids: list[UUID],
                            recognition_only: bool = False) -> dict[UUID, datetime]: ...


class VideoWordLinks(Protocol):
    def for_video(self, user_id: UUID, library_item_id: UUID) -> set[UUID] | None: ...
    def add(self, user_id: UUID, library_item_id: UUID, concept_id: UUID) -> None: ...


def _region_source(request) -> dict:
    """A word saved from a lookup in a study region counts for that region's result."""
    region = getattr(request, "region_id", None)
    return {"source_type": "video_region", "source_id": region} if split_region_id(region or "") else {}


class MyWordsService:
    def __init__(self, *, saved: SavedConceptStore, resolver: WordConceptResolver,
                 concepts: ConceptListReader, reviews: NextReviewReader,
                 preferences: LanguagePreferenceStore, targets: WordTargetsService | None = None,
                 video_words: VideoWordLinks | None = None, readings=None, learning_log=None):
        self.learning_log = learning_log  # the learning log (activity module); None = not recording
        self.readings = readings
        self.video_words = video_words
        self.targets = targets
        self.saved = saved
        self.resolver = resolver
        self.concepts = concepts
        self.reviews = reviews
        self.preferences = preferences

    def save(self, user: CurrentUser, request: SaveFromLookup | SaveFromDictionary | SaveFromOccurrence) -> MyWordView:
        try:
            result = self._save(user, request)
            if self.video_words is not None and isinstance(request, (SaveFromLookup, SaveFromOccurrence)):
                self.video_words.add(user.id, request.library_item_id, result.concept_id)
            return result
        except MyWordsError:
            raise
        except ValueError as exc:
            # Content's request errors (not found, sense not offered) keep their status and code.
            status_code, code = getattr(exc, "status_code", None), getattr(exc, "code", None)
            if isinstance(status_code, int) and isinstance(code, str):
                raise MyWordsError(str(exc), status_code=status_code, code=code) from exc
            raise

    def _save(self, user: CurrentUser, request) -> MyWordView:
        occurrence = None
        if isinstance(request, SaveFromLookup):
            concept = self.resolver.from_lookup(
                user, request.library_item_id, segment_id=request.segment_id,
                start_codepoint=request.start_codepoint, end_codepoint=request.end_codepoint,
                sense_id=request.sense_id,
            )
            source = SaveSource.LOOKUP
        elif isinstance(request, SaveFromDictionary):
            language = request.language_code.strip().casefold()
            if self.preferences.get_by_language_for_user(user_id=user.id, language_code=language) is None:
                raise MyWordsError("You are not learning this language.", status_code=422,
                                   code="language_not_learned")
            concept = self.resolver.from_dictionary(language_code=language, entry_id=request.entry_id,
                                                    sense_id=request.sense_id)
            source = SaveSource.MANUAL
        else:
            concept = self.resolver.from_occurrence(user, request.library_item_id, request.learning_object_id)
            source, occurrence = SaveSource.OCCURRENCE, request.learning_object_id
        if concept.id is None:
            raise MyWordsError("This word cannot be saved right now.", status_code=503, code="word_unavailable")
        if self.targets is not None:
            try:
                row = self.targets.register(
                    user, concept, save_source=source.value, explicit=True, priority=PRIORITY_EXPLICIT,
                    source_learning_object_id=occurrence,
                    acknowledge_above_level=bool(getattr(request, "acknowledge_above_level", False)))
            except WordTargetsError as exc:
                raise MyWordsError(str(exc), status_code=exc.status_code, code=exc.code, extra=exc.extra) from exc
            saved = SavedWord(**row)
        else:
            saved = SavedWord(**self.saved.save(user.id, concept_id=concept.id, save_source=source.value,
                                                source_learning_object_id=occurrence))
        # One fact per word however often it is saved again or the request is retried.
        log_activity(self.learning_log, user_id=user.id, language_code=concept.language_code,
                     client_event_id=f"word_saved:{concept.id}", kind="word_saved", outcome="done",
                     item_type="concept", item_id=str(concept.id), detail={"save_source": source.value},
                     **_region_source(request))
        return self._views([saved], {concept.id: concept}, user)[0]

    def remove(self, user: CurrentUser, concept_id: UUID) -> None:
        """Removes the word from My words."""
        if not self.saved.remove(user.id, concept_id=concept_id):
            raise MyWordsError("Word not found.", status_code=404, code="word_not_found")

    def set_status(self, user: CurrentUser, concept_id: UUID, status: TargetStatus) -> MyWordView:
        """Pause a word or resume it; legacy backlog requests mean active."""
        if self.targets is None:
            raise MyWordsError("Word status is not available.", status_code=503, code="targets_unavailable")
        try:
            row = self.targets.set_status(user, concept_id, status)
        except WordTargetsError as exc:
            raise MyWordsError(str(exc), status_code=exc.status_code, code=exc.code, extra=exc.extra) from exc
        concept = next(iter(self.concepts.list_by_ids([concept_id])), None)
        if concept is None:
            raise MyWordsError("Word not found.", status_code=404, code="word_not_found")
        return self._views([SavedWord(**row)], {concept_id: concept}, user)[0]

    def list(self, user: CurrentUser, language_code: str | None = None,
             library_item_id: UUID | None = None, *, recognition_only: bool = False) -> MyWordsView:
        linked = None
        if library_item_id is not None:
            if self.video_words is None:
                raise MyWordsError("Video words are unavailable.", status_code=503, code="video_words_unavailable")
            linked = self.video_words.for_video(user.id, library_item_id)
            if linked is None:
                raise MyWordsError("Video not found in your Library.", status_code=404, code="library_item_not_found")
        language = language_code.strip().casefold() if language_code else None
        saved = [SavedWord(**row) for row in self.saved.list_for_user(user.id)]
        ids = list(dict.fromkeys(item.concept_id for item in saved))
        if linked is not None:
            ids = [concept_id for concept_id in ids if concept_id in linked]
        concepts = {item.id: item for item in (self.concepts.list_by_ids(ids) if ids else [])
                    if language is None or item.language_code == language}
        views = self._views(saved, concepts, user, recognition_only=recognition_only)
        summary = None
        if self.targets is not None and language:
            summary = self.targets.summary(
                user.id, language, [item.status for item in saved if item.language_code == language])
        return MyWordsView(words=views, summary=summary)

    def _readings(self, concepts) -> dict[UUID, tuple[str | None, str | None]]:
        if self.readings is None:
            return {}
        by_language: dict[str, list] = {}
        for concept in concepts:
            by_language.setdefault(concept.language_code, []).append(concept)
        found: dict[UUID, tuple[str | None, str | None]] = {}
        for language, items in by_language.items():
            values = self.readings.readings_for(language, [item.canonical_text for item in items])
            found.update({item.id: values[item.canonical_text] for item in items if item.canonical_text in values})
        return found

    def set_personal(self, user: CurrentUser, concept_id: UUID, fields: dict) -> MyWordView:
        """The learner's own note and favourite. None of them changes the schedule or the rung."""
        row = self.saved.update_personal(user.id, concept_id=concept_id, fields=fields)
        if row is None:
            raise MyWordsError("Word not found.", status_code=404, code="word_not_found")
        concept = self.concepts.get_by_id(concept_id)
        if concept is None:
            raise MyWordsError("Word not found.", status_code=404, code="word_not_found")
        return self._views([SavedWord(**row)], {concept_id: concept}, user)[0]

    def _views(self, saved: list[SavedWord], concepts: dict, user: CurrentUser, *,
               recognition_only: bool = False) -> list[MyWordView]:
        saved_by_id = {item.concept_id: item for item in saved}
        order = list(dict.fromkeys(item.concept_id for item in saved))
        ids = [concept_id for concept_id in order if concept_id in concepts]
        due = self.reviews.next_due_by_concept(user_id=user.id, concept_ids=ids,
                                               **({"recognition_only": True} if recognition_only else {})) if ids else {}
        views = []
        declared: dict[str, str | None] = {}
        readings = self._readings(concepts[concept_id] for concept_id in ids)
        for concept_id in ids:
            concept = concepts[concept_id]
            entry = saved_by_id.get(concept_id)
            if self.targets is not None and concept.language_code not in declared:
                declared[concept.language_code] = self.targets.settings(user.id, concept.language_code).declared_level
            gloss = (concept.metadata or {}).get("sense_gloss")
            views.append(MyWordView(
                concept_id=concept_id, language_code=concept.language_code, text=concept.canonical_text,
                kind=concept.type.value if hasattr(concept.type, "value") else str(concept.type),
                gloss=gloss if isinstance(gloss, str) else None,
                list=ConceptList.SAVED,
                saved=entry is not None and entry.explicit, save_source=entry.save_source if entry else None,
                added_at=entry.created_at if entry else None,
                next_review_at=due.get(concept_id),
                status="active" if entry is None or entry.status == "backlog" else entry.status,
                explicit=entry.explicit if entry else False, priority=entry.priority if entry else 0,
                level_label=entry.level_label if entry else None, rung=entry.rung if entry else 0,
                above_level=bool(entry and is_above_level(concept.language_code, entry.level_label,
                                                          declared.get(concept.language_code))),
                reading=readings.get(concept_id, (None, None))[0], traditional=readings.get(concept_id, (None, None))[1],
                note=entry.note if entry else None, favorite=entry.favorite if entry else False,
            ))
        return views
