from datetime import UTC, datetime

from fsrs import Card, Rating, Scheduler, State

from app.modules.review.domain.scheduling import FSRSTransition
from app.modules.review.domain.models import (
    FSRSState,
    REVIEW_RATING_TO_FSRS_VALUE,
    ReviewGrade,
    ReviewState,
)


class FSRSAdapter:
    def __init__(self, scheduler: Scheduler | None = None):
        self.scheduler = scheduler or Scheduler(enable_fuzzing=False)

    def apply(self, *, review_state: ReviewState, grade: ReviewGrade,
              reviewed_at: datetime | None = None) -> FSRSTransition:
        previous = review_state.model_copy(deep=True)
        scheduled_card, review_log = self.scheduler.review_card(
            _card_from_review_state(review_state),
            _rating_from_grade(grade),
            **({'review_datetime': _ensure_utc(reviewed_at)} if reviewed_at is not None else {}),
        )
        reviewed_at = _ensure_utc(review_log.review_datetime)
        return FSRSTransition(
            previous_state=previous,
            review_state=_review_state_from_card(
                previous=review_state,
                card=scheduled_card,
                reviewed_at=reviewed_at,
                grade=grade,
            ),
            reviewed_at=reviewed_at,
        )


def _card_from_review_state(state: ReviewState) -> Card:
    return Card(
        state=_fsrs_state(state.state),
        stability=state.stability if state.stability > 0 else None,
        difficulty=state.difficulty if state.difficulty > 0 else None,
        due=_ensure_utc(state.due_at),
        last_review=_ensure_utc(state.last_reviewed_at) if state.last_reviewed_at is not None else None,
    )


def _fsrs_state(state: FSRSState) -> State:
    if state == FSRSState.REVIEW:
        return State.Review
    if state == FSRSState.RELEARNING:
        return State.Relearning
    return State.Learning


def _deep_lingo_state(state: State) -> FSRSState:
    if state == State.Review:
        return FSRSState.REVIEW
    if state == State.Relearning:
        return FSRSState.RELEARNING
    return FSRSState.LEARNING


def _rating_from_grade(grade: ReviewGrade) -> Rating:
    return Rating(REVIEW_RATING_TO_FSRS_VALUE[grade])


def _review_state_from_card(
    *,
    previous: ReviewState,
    card: Card,
    reviewed_at: datetime,
    grade: ReviewGrade,
) -> ReviewState:
    due_at = _ensure_utc(card.due)
    elapsed_days = 0
    if previous.last_reviewed_at is not None:
        elapsed_days = max((reviewed_at.date() - _ensure_utc(previous.last_reviewed_at).date()).days, 0)
    scheduled_days = max((due_at.date() - reviewed_at.date()).days, 0)
    return previous.model_copy(
        update={
            "state": _deep_lingo_state(card.state),
            "stability": round(float(card.stability or 0), 4),
            "difficulty": round(float(card.difficulty or 0), 4),
            "elapsed_days": elapsed_days,
            "scheduled_days": scheduled_days,
            "reps": previous.reps + 1,
            "lapses": previous.lapses + (1 if REVIEW_RATING_TO_FSRS_VALUE[grade] == 1 else 0),
            "version": previous.version + 1,
            "due_at": due_at,
            "last_reviewed_at": reviewed_at,
        }
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
