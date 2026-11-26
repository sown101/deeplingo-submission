"""Grammar practice from the owner-approved banks: lessons and exercises, no FSRS (PRD 8.10).

The banks hold choice questions only, so every grammar exercise is a choice; the bank's answer key never leaves
the server before the learner has answered.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.content.contracts import GrammarBank


@dataclass(frozen=True)
class FoundQuestion:
    bank: GrammarBank
    point: Any
    question: Any


def find_point(banks: list[GrammarBank], grammar_key: str):
    for bank in banks:
        for point in bank.points:
            if point.key == grammar_key:
                return bank, point
    return None


def find_question(banks: list[GrammarBank], question_id: str) -> FoundQuestion | None:
    for bank in banks:
        for point in bank.points:
            if not question_id.startswith(point.key + "."):
                continue
            for question in point.questions:
                if question.id == question_id:
                    return FoundQuestion(bank, point, question)
    return None


def exercise_view(point, question) -> dict[str, Any]:
    """A question as the learner sees it: no answer key, no explanation."""
    return {"id": question.id, "grammar_key": point.key, "type": "choice", "prompt": question.prompt,
            "options": [option.model_dump() for option in question.options]}


def lesson_view(point) -> dict[str, Any] | None:
    return point.lesson.model_dump(mode="json") if point.lesson else None


def grade_question(question, option_id: str) -> bool:
    if option_id not in {option.id for option in question.options}:
        raise ValueError("unknown_option")
    return question.correct_option_id == option_id
