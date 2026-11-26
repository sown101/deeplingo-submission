"""The one review engine for words: a deck per language, any exercise type, one answer path (TARGET_DESIGN 5).

`due` builds the exercises of a review pass on the server; the client runs the pass and sends each answer to
`answer`, which grades it, moves the FSRS schedule and writes one learning-log row in one database transaction
(`v3.submit_review_answer`). A card's schedule changes at most once per pass: a second answer to the same card in
the same pass is graded and logged but leaves the schedule alone. A retried answer (same client_event_id) is
stored once and returns the stored result. Pronunciation and writing are practice only (owner decision 2026-11-14):
they are graded and logged but never move the schedule.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.modules.practice.domain.exercises import (
    EXERCISE_TYPES,
    MIXED_ORDER,
    UNSCHEDULED_TYPES,
    ExerciseUnavailable,
    Graded,
    WordCard,
    generate_with_fallback,
    grade,
    grade_pronunciation,
)
from app.modules.review.contracts import (
    SELF_RATINGS,
    ReviewEvent,
    ReviewState,
    grade_for_result,
    grade_for_self_rating,
    initial_review_state,
    is_fast,
    scheduling_snapshot,
    serialize_review_event_for_insert,
)

if TYPE_CHECKING:  # concrete classes, wired in bootstrap
    from app.modules.practice.infrastructure.repositories import ReviewDeckRepository
    from app.modules.practice.infrastructure.word_cards import WordCards

logger = logging.getLogger(__name__)

MAX_CARDS = 50
MAX_COMMIT_TRIES = 3
PROVENANCE = "review_answer"


class PracticeError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str):
        super().__init__(message)
        self.status_code, self.code = status_code, code


@dataclass(frozen=True)
class ReviewAnswer:
    """One answer as the client sends it: selectors and the learner's own input, never a result."""
    user_id: UUID
    concept_id: UUID
    language_code: str
    exercise_type: str
    client_event_id: str
    pass_id: str | None = None
    answer: dict[str, Any] = field(default_factory=dict)
    hint_used: bool = False
    response_ms: int | None = None


class ReviewService:
    def __init__(self, *, store: "ReviewDeckRepository", cards: "WordCards", adapter,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.store, self.cards, self.adapter, self.clock = store, cards, adapter, clock

    # --- Reading ------------------------------------------------------------------------------------------------

    def decks(self, user_id: UUID) -> list[dict[str, Any]]:
        """Due and new cards of every language the learner has saved words in; a deck never mixes languages."""
        return sorted(self.store.deck_counts(user_id), key=lambda deck: deck["language_code"])

    def due(self, user_id: UUID, language_code: str, *, mode: str = "mixed", limit: int = 20,
            concept_ids: list[UUID] | None = None, types: list[str] | None = None) -> dict[str, Any]:
        """Due cards first, then new cards (newest save first); with `concept_ids`, exactly those saved words.

        With `types` (the notebook's review settings) the cards take those types in turn; a card that cannot make
        its type tries the other chosen types and is left out when none fits.
        """
        if mode != "mixed" and mode not in EXERCISE_TYPES:
            raise PracticeError("Unknown exercise type.", status_code=422, code="exercise_type_invalid")
        chosen = tuple(dict.fromkeys(types or ()))
        if any(kind not in EXERCISE_TYPES for kind in chosen):
            raise PracticeError("Unknown exercise type.", status_code=422, code="exercise_type_invalid")
        limit = max(1, min(limit, MAX_CARDS))
        rows = self.store.deck_cards(user_id, language_code, limit=limit, concept_ids=concept_ids)
        counts = next((deck for deck in self.store.deck_counts(user_id) if deck["language_code"] == language_code),
                      {"due_count": 0, "new_count": 0})
        cards = self.cards.cards(user_id, language_code, [row["concept_id"] for row in rows])
        pools = {"meaning_pool": self.cards.meaning_pool(user_id, language_code),
                 "word_pool": [card.text for card in cards.values()] + self.cards.word_pool(language_code)}
        views = []
        for row in rows:
            card = cards.get(row["concept_id"])
            if card is None or card.language_code != language_code:
                continue
            seed = f"{user_id}:{card.concept_id}"
            try:
                if chosen:
                    wanted = chosen[len(views) % len(chosen)]
                    exercise = generate_with_fallback(wanted, card, fallback=chosen, seed=seed, **pools)
                else:
                    wanted = mode if mode != "mixed" else MIXED_ORDER[len(views) % len(MIXED_ORDER)]
                    exercise = generate_with_fallback(wanted, card, seed=seed, **pools)
            except ExerciseUnavailable:
                continue
            views.append({"concept_id": card.concept_id, "text": card.text, "reading": card.reading,
                          "is_new": bool(row["is_new"]), "due_at": row.get("due_at"),
                          "exercise": {"type": exercise.type, "prompt": exercise.prompt}})
        return {"language_code": language_code, "due_count": int(counts["due_count"]),
                "new_count": int(counts["new_count"]), "cards": views}

    def card(self, user_id: UUID, concept_id: UUID) -> WordCard:
        """A saved word of the learner in any language (for its audio); 404 when it is not theirs."""
        context = self.store.answer_context(user_id, concept_id, None) or {}
        language = context.get("language_code")
        found = self.cards.cards(user_id, language, [concept_id]).get(concept_id) if (
            context.get("eligible") and language) else None
        if found is None:
            raise PracticeError("This word is not being reviewed.", status_code=404, code="word_not_in_review")
        return found

    # --- Answering ----------------------------------------------------------------------------------------------

    def answer(self, request: ReviewAnswer) -> dict[str, Any]:
        if request.exercise_type not in EXERCISE_TYPES or request.exercise_type == "pronunciation":
            raise PracticeError("Unknown exercise type.", status_code=422, code="exercise_type_invalid")
        if request.exercise_type == "flashcard" and request.answer.get("rating") not in SELF_RATINGS:
            raise PracticeError("Choose how well you remembered the word.", status_code=422,
                                code="flashcard_rating_required")
        card = self._card(request)
        try:
            graded = grade(request.exercise_type, card, request.answer)
        except ExerciseUnavailable as exc:
            raise PracticeError("This exercise is not available for this word.", status_code=409,
                                code="exercise_unavailable") from exc
        return self._commit(request, card, graded)

    def rate_memory(self, user_id: UUID, concept_id: UUID, rating: str, client_event_id: str):
        """The notebook flashcard ("not yet / unsure / remembered") as a flashcard answer outside any pass;
        returns the next review time."""
        context = self.store.answer_context(user_id, concept_id, None) or {}
        if not context.get("eligible") or not context.get("language_code"):
            raise PracticeError("This word is not being reviewed.", status_code=409, code="word_not_in_review")
        result = self.answer(ReviewAnswer(user_id=user_id, concept_id=concept_id,
                                          language_code=context["language_code"], exercise_type="flashcard",
                                          client_event_id=client_event_id, answer={"rating": rating}))
        return result["next_review_at"]

    def answer_pronunciation(self, request: ReviewAnswer, *, band: str, score: float,
                             assessment: dict[str, Any] | None = None) -> dict[str, Any]:
        """`assessment` is Azure's whole result; it is kept on the log row, so the latest one is the word's."""
        card = self._card(request)
        return self._commit(request, card, grade_pronunciation(card, band=band, score=score, assessment=assessment))

    def latest_pronunciation(self, user_id: UUID, concept_id: UUID) -> dict[str, Any] | None:
        """The learner's most recent pronunciation result for a word, from the learning log."""
        return self.store.latest_pronunciation(user_id, concept_id)

    def pronunciation_text(self, request: ReviewAnswer) -> str:
        return self._card(request).text

    def _card(self, request: ReviewAnswer) -> WordCard:
        card = self.cards.cards(request.user_id, request.language_code, [request.concept_id]).get(request.concept_id)
        if card is None or card.language_code != request.language_code:
            raise PracticeError("This word is not being reviewed.", status_code=409, code="word_not_in_review")
        return card

    def _grade(self, request: ReviewAnswer, graded: Graded, context: dict[str, Any]):
        if request.exercise_type == "flashcard":
            return grade_for_self_rating(str(request.answer.get("rating")))
        last = context.get("last_result") or {}
        return grade_for_result(correct=graded.correct, hint_used=request.hint_used or graded.outcome == "partial",
                                fast=is_fast(request.response_ms),
                                previous_fast_correct=last.get("outcome") == "correct" and last.get("fast") is True)

    def _commit(self, request: ReviewAnswer, card: WordCard, graded: Graded) -> dict[str, Any]:
        event_id = f"review:{request.client_event_id}"
        for _ in range(MAX_COMMIT_TRIES):
            context = self.store.answer_context(request.user_id, card.concept_id, request.pass_id) or {}
            review_grade = self._grade(request, graded, context)
            transition, now = None, self.clock()
            if (context.get("eligible") and not context.get("scheduled_in_pass")
                    and request.exercise_type not in UNSCHEDULED_TYPES):
                transition = self._transition(request.user_id, card.concept_id, context, review_grade, now)
            fast = graded.correct and is_fast(request.response_ms)
            log = {"client_event_id": event_id, "language_code": card.language_code, "kind": request.exercise_type,
                   "outcome": graded.outcome, "score": graded.score, "source_id": request.pass_id,
                   "detail": {**graded.detail, "grade": review_grade.value, "correct": graded.correct,
                              "hint": request.hint_used, "fast": fast}}
            stored = self.store.submit_answer(request.user_id, card.concept_id, transition, log)
            status = stored.get("status")
            if status == "conflict":
                continue
            if status == "skipped":
                raise PracticeError("This word is not being reviewed.", status_code=409, code="word_not_in_review")
            if status == "duplicate":
                detail = stored.get("detail") or {}
                return self._view(request, card, outcome=stored.get("outcome"), correct=bool(detail.get("correct")),
                                  grade=detail.get("grade"), scheduled=bool(detail.get("scheduled")),
                                  next_review_at=detail.get("next_review_at"), expected=graded.expected,
                                  duplicate=True)
            if status not in {"applied", "graded"}:
                raise RuntimeError("Unconfirmed review answer commit")
            return self._view(request, card, outcome=graded.outcome, correct=graded.correct, grade=review_grade.value,
                              scheduled=status == "applied", next_review_at=stored.get("next_review_at"),
                              expected=graded.expected, duplicate=False)
        raise PracticeError("Please try again.", status_code=409, code="review_changed")

    def _transition(self, user_id: UUID, concept_id: UUID, context: dict[str, Any], review_grade,
                    now: datetime) -> dict[str, Any]:
        state = ReviewState(**context["review_state"]) if context.get("review_state") else None
        previous = state or initial_review_state(user_id=user_id, concept_id=concept_id, due_at=now)
        if previous.id is None:
            previous = previous.model_copy(update={"id": uuid4()})
        result = self.adapter.apply(review_state=previous, grade=review_grade, reviewed_at=now)
        event = ReviewEvent(review_state_id=previous.id, review_mode=previous.review_mode, rating=review_grade,
                            previous_scheduling_state=scheduling_snapshot(previous),
                            resulting_scheduling_state=scheduling_snapshot(result.review_state),
                            reviewed_at=now, provenance=PROVENANCE)
        return {"previous": scheduling_snapshot(previous), "next": scheduling_snapshot(result.review_state),
                "event": serialize_review_event_for_insert(event), "create": state is None}

    @staticmethod
    def _view(request: ReviewAnswer, card: WordCard, **fields) -> dict[str, Any]:
        return {"client_event_id": request.client_event_id, "concept_id": card.concept_id,
                "exercise_type": request.exercise_type, **fields}
