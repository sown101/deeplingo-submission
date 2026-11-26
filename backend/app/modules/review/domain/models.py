from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator



class ReviewMode(str, Enum):
    CONCEPT_TO_MEANING = "concept_to_meaning"
    MEANING_TO_CONCEPT = "meaning_to_concept"
    AUDIO_TO_TEXT = "audio_to_text"
    TEXT_TO_MEANING = "text_to_meaning"
    PRODUCTION_PROMPT = "production_prompt"
    SHADOWING_PROMPT = "shadowing_prompt"


class FSRSState(str, Enum):
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class ReviewRating(str, Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


ReviewGrade = ReviewRating


REVIEW_RATING_TO_FSRS_VALUE = {
    ReviewRating.AGAIN: 1,
    ReviewRating.HARD: 2,
    ReviewRating.GOOD: 3,
    ReviewRating.EASY: 4,
}


class ReviewState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID | None = None
    user_id: UUID
    concept_id: UUID
    review_mode: ReviewMode = ReviewMode.CONCEPT_TO_MEANING
    state: FSRSState = Field(default=FSRSState.NEW, alias="fsrs_state")
    due_at: datetime
    stability: float = Field(default=0, ge=0)
    difficulty: float = Field(default=0, ge=0, le=10)
    elapsed_days: int = Field(default=0, ge=0)
    scheduled_days: int = Field(default=0, ge=0)
    reps: int = Field(default=0, ge=0)
    lapses: int = Field(default=0, ge=0)
    version: int = Field(default=0, ge=0)
    last_reviewed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_initial_state(self) -> "ReviewState":
        if self.state == FSRSState.NEW:
            if self.reps != 0:
                raise ValueError("new review state cannot have reps")
            if self.lapses != 0:
                raise ValueError("new review state cannot have lapses")
            if self.last_reviewed_at is not None:
                raise ValueError("new review state cannot have last_reviewed_at")
        return self


class ReviewEvent(BaseModel):
    id: UUID | None = None
    review_state_id: UUID
    attempt_id: UUID | None = None
    review_mode: ReviewMode
    rating: ReviewRating
    previous_scheduling_state: dict[str, Any]
    resulting_scheduling_state: dict[str, Any]
    reviewed_at: datetime
    created_at: datetime | None = None
    provenance: str | None = None

    @field_validator("rating", mode="before")
    @classmethod
    def parse_fsrs_rating(cls, value) -> ReviewRating:
        if isinstance(value, ReviewRating):
            return value
        if isinstance(value, int):
            for rating, fsrs_value in REVIEW_RATING_TO_FSRS_VALUE.items():
                if fsrs_value == value:
                    return rating
        return ReviewRating(value)

    @field_validator("previous_scheduling_state", "resulting_scheduling_state")
    @classmethod
    def reject_payload_leaks(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {
            "answer",
            "answers",
            "expected_answer",
            "expected_response",
            "prompt",
            "prompts",
            "raw_ai_diagnostics",
            "model_metadata",
            "llm",
            "transcript",
            "response_payload",
        }
        keys = _flatten_keys(value)
        leaked = sorted(key for key in keys if key in forbidden)
        if leaked:
            raise ValueError("review event scheduling snapshots cannot contain answer, prompt, or model diagnostics")
        return value


def initial_review_state(
    *,
    user_id: UUID,
    concept_id: UUID,
    review_mode: ReviewMode = ReviewMode.CONCEPT_TO_MEANING,
    due_at: datetime | None = None,
) -> ReviewState:
    return ReviewState(
        user_id=user_id,
        concept_id=concept_id,
        review_mode=review_mode,
        due_at=due_at or datetime.now(UTC),
        state=FSRSState.NEW,
        stability=0,
        difficulty=0,
        elapsed_days=0,
        scheduled_days=0,
        reps=0,
        lapses=0,
        last_reviewed_at=None,
    )


def serialize_review_event_for_insert(event: ReviewEvent) -> dict[str, Any]:
    payload = event.model_dump()
    payload.pop("id", None)
    payload.pop("created_at", None)
    payload["review_state_id"] = str(event.review_state_id)
    payload["attempt_id"] = str(event.attempt_id) if event.attempt_id else None
    payload["review_mode"] = event.review_mode.value
    payload["rating"] = REVIEW_RATING_TO_FSRS_VALUE[event.rating]
    payload["reviewed_at"] = event.reviewed_at.isoformat()
    payload["provenance"] = event.provenance or "review_update_policy"
    return payload


def scheduling_snapshot(review_state: ReviewState) -> dict[str, Any]:
    return {
        "review_state_id": str(review_state.id) if review_state.id else None,
        "user_id": str(review_state.user_id),
        "concept_id": str(review_state.concept_id),
        "review_mode": review_state.review_mode.value,
        "fsrs_state": review_state.state.value,
        "stability": review_state.stability,
        "difficulty": review_state.difficulty,
        "elapsed_days": review_state.elapsed_days,
        "scheduled_days": review_state.scheduled_days,
        "reps": review_state.reps,
        "lapses": review_state.lapses,
        "version": review_state.version,
        "due_at": review_state.due_at.isoformat(),
        "last_reviewed_at": review_state.last_reviewed_at.isoformat() if review_state.last_reviewed_at else None,
    }


def _flatten_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys: set[str] = set()
        for key, nested in value.items():
            keys.add(str(key).casefold())
            keys.update(_flatten_keys(nested))
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys.update(_flatten_keys(item))
        return keys
    return set()
