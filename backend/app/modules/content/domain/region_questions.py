"""M1 S6 region comprehension questions: global practice content of one prepared study region.

A model proposes up to three multiple-choice questions about the region's sentences; the validator
keeps only questions whose four options are distinct, whose answer is one of them and whose quote is
an exact part of the cited region sentence. Answers are practice only: they never become Attempts,
Evidence, mastery, skills or review scheduling.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

REGION_QUESTION_VALIDATION_VERSION = "region_questions_validator_v1"
MAX_REGION_QUESTIONS = 3
OPTION_COUNT = 4
MAX_QUESTION_CHARS = 300
MAX_OPTION_CHARS = 120
MAX_QUOTE_CHARS = 300
MAX_EXPLANATION_CHARS = 400
MIN_QUOTE_CHARS = 2

RegionQuestionsStatus = Literal["ready", "none", "failed"]


def _clean(value: str) -> str:
    return " ".join((value or "").split())


class LLMRegionQuestion(BaseModel):
    """One proposed question. Bounds are enforced here; grounding is checked by the validator."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    options: list[str] = Field(min_length=OPTION_COUNT, max_length=OPTION_COUNT)
    correct_index: int = Field(ge=0, le=OPTION_COUNT - 1)
    evidence_ref: str = Field(pattern=r"^s[1-9][0-9]{0,2}$")
    evidence_quote: str = Field(min_length=MIN_QUOTE_CHARS, max_length=MAX_QUOTE_CHARS)
    explanation: str = Field(min_length=1, max_length=MAX_EXPLANATION_CHARS)

    @field_validator("options")
    @classmethod
    def bounded_options(cls, value: list[str]) -> list[str]:
        if any(not _clean(item) or len(item) > MAX_OPTION_CHARS for item in value):
            raise ValueError("Options must be short and non-empty")
        return value


class LLMRegionQuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[LLMRegionQuestion] = Field(max_length=MAX_REGION_QUESTIONS)


@dataclass(frozen=True)
class RegionSentence:
    """A region sentence as the model sees it: `s1`..`sN` in region order."""

    ref: str
    segment_id: UUID
    text: str


class RegionQuestion(BaseModel):
    """A stored question. `correct_index` stays on the server until the learner answers."""

    id: UUID
    region_preparation_id: UUID
    position: int
    question: str
    options: list[str]
    correct_index: int
    evidence_segment_id: UUID
    evidence_quote: str
    explanation: str
    generation_version: str


def _key(text: str) -> str:
    return _clean(unicodedata.normalize("NFKC", text)).casefold()


def validate_region_questions(
    proposed: LLMRegionQuestionSet, sentences: list[RegionSentence], *, generation_version: str,
    rejected: Counter | None = None,
) -> list[dict]:
    """Questions that pass every check, ready for the fenced write; the rest are dropped.

    `rejected`, when given, counts each dropped question by reason (no question text is kept).
    """
    by_ref = {sentence.ref: sentence for sentence in sentences}
    kept: list[dict] = []
    seen: set[str] = set()
    for item in proposed.questions:
        question = _clean(item.question)
        options = [_clean(option) for option in item.options]
        explanation = _clean(item.explanation)
        sentence = by_ref.get(item.evidence_ref)
        # The quote is copied, not cleaned: it must be an exact part of the cited sentence.
        quote = item.evidence_quote.strip()
        reason = None
        if not question or not explanation:
            reason = "empty"
        elif sentence is None:
            reason = "unknown_ref"
        elif len(quote) < MIN_QUOTE_CHARS or quote not in sentence.text:
            reason = "quote_not_in_sentence"
        elif len({_key(option) for option in options}) != OPTION_COUNT:
            reason = "options_not_distinct"
        elif _key(question) in seen:
            reason = "duplicate"
        if reason is not None:
            if rejected is not None:
                rejected[reason] += 1
            continue
        seen.add(_key(question))
        kept.append({
            "question": question, "options": options, "correct_index": item.correct_index,
            "evidence_segment_id": str(sentence.segment_id), "evidence_quote": quote,
            "explanation": explanation, "generation_version": generation_version,
        })
        if len(kept) == MAX_REGION_QUESTIONS:
            break
    return kept
