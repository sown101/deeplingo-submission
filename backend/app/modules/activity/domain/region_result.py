"""What the learner did in one study region, summed from the learning log (PRD 8.10, TARGET_DESIGN section 6)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.modules.activity.domain.models import ActivityRecord


class RegionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str
    dictation_attempts: int = 0
    dictation_sentences: int = 0
    dictation_accuracy: float | None = None  # mean of the attempts' word scores, 0-100
    shadowing_attempts: int = 0
    shadowing_sentences: int = 0
    shadowing_average: float | None = None  # mean of the attempts' pronunciation scores, 0-100
    questions_answered: int = 0
    questions_correct: int = 0
    lookups: int = 0
    words_saved: int = 0
    practised: bool = False


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def region_result(region_id: str, rows: list[ActivityRecord]) -> RegionResult:
    """`rows` are the learner's own rows of this region, newest first. A question counts once, by its latest answer."""
    dictation = [row for row in rows if row.kind == "dictation"]
    shadowing = [row for row in rows if row.kind == "shadowing"]
    latest_answer: dict[str, str] = {}
    for row in rows:
        if row.kind == "region_question":
            latest_answer.setdefault(str(row.detail.get("question_id") or row.item_id or row.id), row.outcome)
    result = RegionResult(
        region_id=region_id,
        dictation_attempts=len(dictation), dictation_sentences=len({row.item_id for row in dictation}),
        dictation_accuracy=_mean([row.score for row in dictation if row.score is not None]),
        shadowing_attempts=len(shadowing), shadowing_sentences=len({row.item_id for row in shadowing}),
        shadowing_average=_mean([row.score for row in shadowing if row.score is not None]),
        questions_answered=len(latest_answer),
        questions_correct=sum(1 for outcome in latest_answer.values() if outcome == "correct"),
        lookups=sum(1 for row in rows if row.kind == "lookup"),
        words_saved=sum(1 for row in rows if row.kind == "word_saved"),
    )
    return result.model_copy(update={"practised": bool(dictation or shadowing or latest_answer)})
