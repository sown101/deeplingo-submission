"""The one mapping from a learner's result to an FSRS grade (TARGET_DESIGN section 5).

A flashcard is graded by the learner's own rating. Every other exercise is graded by the server: a wrong answer
is Again, a right answer after a hint is Hard, a right answer is Good, and a fast right answer that follows a
fast right answer on the same card is Easy.
"""
from __future__ import annotations

from app.modules.review.domain.models import ReviewGrade

# The learner's own ratings, and the notebook flashcard labels the web sends.
SELF_RATINGS: dict[str, ReviewGrade] = {
    "again": ReviewGrade.AGAIN, "hard": ReviewGrade.HARD, "good": ReviewGrade.GOOD, "easy": ReviewGrade.EASY,
    "not_yet": ReviewGrade.AGAIN, "unsure": ReviewGrade.HARD, "remembered": ReviewGrade.GOOD,
}
# A right answer given within this time counts as fast.
FAST_ANSWER_MS = 6000


def grade_for_self_rating(rating: str) -> ReviewGrade:
    try:
        return SELF_RATINGS[rating]
    except KeyError:
        raise ValueError("unknown rating") from None


def is_fast(response_ms: int | None) -> bool:
    return response_ms is not None and 0 <= response_ms <= FAST_ANSWER_MS


def grade_for_result(*, correct: bool, hint_used: bool = False, fast: bool = False,
                     previous_fast_correct: bool = False) -> ReviewGrade:
    if not correct:
        return ReviewGrade.AGAIN
    if hint_used:
        return ReviewGrade.HARD
    if fast and previous_fast_correct:
        return ReviewGrade.EASY
    return ReviewGrade.GOOD
