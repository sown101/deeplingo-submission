"""Offline contract for DeepLingo's own grammar-question banks.

Validation checks structure and review integrity, not linguistic correctness. A bank
becomes eligible for release only after the owner approves a sample of this exact content.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class GrammarOption(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,20}$")
    text: str = Field(min_length=1, max_length=240)


class GrammarQuestion(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,119}$")
    prompt: str = Field(min_length=1, max_length=800)
    options: tuple[GrammarOption, ...] = Field(min_length=4, max_length=4)
    correct_option_id: str = Field(min_length=1, max_length=20)
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def _answer(self) -> "GrammarQuestion":
        _distinct([option.id for option in self.options], "option id")
        _distinct([_fold(option.text) for option in self.options], "option text")
        if self.correct_option_id not in {option.id for option in self.options}:
            raise ValueError("correct_option_id must name one stored option")
        return self


class GrammarTopic(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,59}$")
    title: str = Field(min_length=1, max_length=120)


class GrammarExample(_Strict):
    text: str = Field(min_length=1, max_length=240)
    meaning: str = Field(min_length=1, max_length=240)


class GrammarMistake(_Strict):
    wrong: str = Field(min_length=1, max_length=200)
    right: str = Field(min_length=1, max_length=200)
    why: str = Field(min_length=1, max_length=300)


class GrammarLesson(_Strict):
    """Short lesson text DeepLingo writes itself for one point; shown before or between questions."""
    summary: str = Field(min_length=1, max_length=400)
    rules: tuple[str, ...] = Field(min_length=1, max_length=6)
    examples: tuple[GrammarExample, ...] = Field(min_length=2, max_length=6)
    mistakes: tuple[GrammarMistake, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def _rule_length(self) -> "GrammarLesson":
        if any(not rule.strip() or len(rule) > 300 for rule in self.rules):
            raise ValueError("each rule must be 1 to 300 characters")
        return self


class GrammarBankPoint(_Strict):
    key: str = Field(pattern=r"^[a-z]{2,3}\.[a-z0-9_]+\.[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=120)
    topic_key: str = Field(min_length=1, max_length=60)
    questions: tuple[GrammarQuestion, ...] = Field(min_length=2, max_length=100)
    lesson: GrammarLesson | None = None

    @model_validator(mode="after")
    def _question_keys(self) -> "GrammarBankPoint":
        if any(not question.id.startswith(self.key + ".") for question in self.questions):
            raise ValueError("question ids must start with their grammar point key")
        return self


class GrammarBankApproval(_Strict):
    reviewer: Literal["owner"]
    approved_on: date
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_question_ids: tuple[str, ...] = Field(min_length=1)


class GrammarBank(_Strict):
    format: Literal["deeplingo-grammar-bank-v1"]
    catalogue_source: Literal["deeplingo"]
    authorship: Literal["ai_draft"]
    language: Literal["en", "zh"]
    level: Literal["A1", "A2", "B1", "B2", "C1", "C2", "HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"]
    support_language: str = Field(pattern=r"^[a-z]{2,3}$")
    version: int = Field(strict=True, ge=1)
    topics: tuple[GrammarTopic, ...] = Field(min_length=1, max_length=60)
    points: tuple[GrammarBankPoint, ...] = Field(min_length=1, max_length=100)
    approval: GrammarBankApproval | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "GrammarBank":
        if (self.language == "en") != (not self.level.startswith("HSK")):
            raise ValueError("English banks use A1 to C2 and Chinese banks use HSK1 to HSK6")
        _distinct([topic.key for topic in self.topics], "topic key")
        _distinct([_fold(topic.title) for topic in self.topics], "topic title")
        _distinct([point.key for point in self.points], "grammar point key")
        topic_keys = {topic.key for topic in self.topics}
        if {point.topic_key for point in self.points} != topic_keys:
            raise ValueError("every point must reference a topic, and every topic must be used")
        prefix = f"{self.language}.{self.level.lower()}."
        if any(not point.key.startswith(prefix) for point in self.points):
            raise ValueError("grammar point keys must start with the bank language and level")
        questions = [question for point in self.points for question in point.questions]
        _distinct([question.id for question in questions], "question id")
        fingerprints = [(_fold(question.prompt), tuple(sorted(_fold(option.text) for option in question.options)))
                        for question in questions]
        _distinct(fingerprints, "question content")
        if self.approval is not None:
            _distinct(list(self.approval.sample_question_ids), "sample question id")
            if not set(self.approval.sample_question_ids) <= {question.id for question in questions}:
                raise ValueError("approval samples must name questions in this bank")
            if self.approval.content_sha256 != self.content_hash():
                raise ValueError("owner approval does not match the current bank content")
        return self

    def content_hash(self) -> str:
        dumped = self.model_dump(mode="json", exclude={"approval"})
        for point in dumped["points"]:
            if point["lesson"] is None:  # banks approved before lessons existed keep their hash
                del point["lesson"]
        content = json.dumps(dumped, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def require_approval(self) -> None:
        if self.approval is None:
            raise ValueError("owner sample approval is required before release")


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _distinct(values: list, label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")
