"""Grammar in the notebook (PRD 8.10, TARGET_DESIGN 5): lessons and exercises from the owner-approved banks,
graded on the server, kept per grammar point in `learner_grammar_progress` and in the learning log. No FSRS.

"Cần làm lại" is the learner's open `grammar_redo` study requests; a correct answer to the same point closes them
in the same transaction that stores the answer (`v3.record_grammar_answer`).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.modules.practice.application.review import PracticeError
from app.modules.practice.domain.grammar import (
    exercise_view,
    find_point,
    find_question,
    grade_question,
    lesson_view,
)

if TYPE_CHECKING:
    from app.modules.practice.infrastructure.repositories import GrammarProgressRepository

DEFAULT_SUPPORT = "vi"


class GrammarService:
    def __init__(self, *, profiles, banks, progress: "GrammarProgressRepository", requests):
        # profiles: the learner's language profile; banks: approved grammar banks (content);
        # requests: the activity module's study requests.
        self.profiles, self.banks, self.progress, self.requests = profiles, banks, progress, requests

    def _support(self, user_id: UUID) -> str:
        profile = self.profiles.get_profile_for_user(user_id)
        if profile is None:
            raise PracticeError("Choose your learning language first.", status_code=409,
                                code="language_profile_required")
        return getattr(profile, "support_language_code", None) or DEFAULT_SUPPORT

    def _banks(self, language: str, support: str) -> list:
        try:
            banks = self.banks.for_language(language, support)
        except Exception as exc:
            raise PracticeError("Grammar is unavailable.", status_code=503, code="grammar_unavailable") from exc
        for bank in banks:
            bank.require_approval()
            if bank.language != language or bank.support_language != support:
                raise PracticeError("bank_language_mismatch", status_code=503, code="grammar_unavailable")
        return banks

    def practice_counts(self, user_id: UUID, language: str) -> tuple[int, dict[str, int]]:
        banks = self._banks(language, self._support(user_id))
        if not banks:
            return 0, {}
        progress = self.progress.for_language(user_id, language)
        practised = {bank.level: sum(int((progress.get(point.key) or {}).get("attempts") or 0) > 0
                                   for point in bank.points) for bank in banks}
        return sum(len(bank.points) for bank in banks), practised

    # --- The notebook's Grammar tab -----------------------------------------------------------------------------

    def overview(self, user_id: UUID, language: str, *, level: str | None = None) -> dict[str, Any]:
        support = self._support(user_id)
        banks = self._banks(language, support)
        view: dict[str, Any] = {"language_code": language, "support_language": support,
                                "levels": [bank.level for bank in banks], "level": None, "topics": [], "points": [],
                                "redo": self._redo(user_id, language, banks)}
        if not banks:
            return view
        bank = next((bank for bank in banks if level is None or bank.level == level), None)
        if bank is None:
            raise PracticeError("Unknown level.", status_code=422, code="grammar_level_unknown")
        progress = self.progress.for_language(user_id, language)
        view.update(level=bank.level, topics=[topic.model_dump() for topic in bank.topics], points=[
            {"key": point.key, "title": point.title, "topic_key": point.topic_key, "lesson": lesson_view(point),
             "exercise_count": len(point.questions), **_progress_view(progress.get(point.key))}
            for point in bank.points])
        return view

    def _redo(self, user_id: UUID, language: str, banks: list) -> list[dict[str, Any]]:
        rows = [row for row in self.requests.study_requests(user_id, language_code=language, status="open")
                if row.kind == "grammar_redo"]
        views = []
        for row in rows:
            found = find_point(banks, row.item_id)
            views.append({"request_id": row.id, "grammar_key": row.item_id,
                          "title": found[1].title if found else row.item_id, "level": found[0].level if found else None,
                          "reason": row.reason, "created_at": row.created_at})
        return views

    def exercises(self, user_id: UUID, language: str, *, level: str | None = None,
                  grammar_key: str | None = None) -> dict[str, Any]:
        banks = self._banks(language, self._support(user_id))
        if grammar_key:
            found = find_point(banks, grammar_key)
            if found is None:
                raise PracticeError("Unknown grammar point.", status_code=404, code="grammar_point_unknown")
            return {"language_code": language, "grammar_key": grammar_key,
                    "exercises": [exercise_view(found[1], question) for question in found[1].questions]}
        bank = next((bank for bank in banks if level is None or bank.level == level), None)
        if bank is None:
            raise PracticeError("Unknown level.", status_code=422, code="grammar_level_unknown")
        return {"language_code": language, "level": bank.level,
                "exercises": [exercise_view(point, question) for point in bank.points for question in point.questions]}

    def answer(self, user_id: UUID, language: str, *, exercise_id: str, option_id: str,
               client_event_id: str) -> dict[str, Any]:
        found = find_question(self._banks(language, self._support(user_id)), exercise_id)
        if found is None:
            raise PracticeError("This exercise changed. Please reload.", status_code=409,
                                code="grammar_exercise_changed")
        try:
            correct = grade_question(found.question, option_id)
        except ValueError as exc:
            raise PracticeError("Unknown option.", status_code=422, code="grammar_option_unknown") from exc
        stored = self.progress.record_answer(user_id, language, found.point.key, {
            "client_event_id": f"grammar_exercise:{client_event_id}", "outcome": "correct" if correct else "incorrect",
            "detail": {"question_id": found.question.id, "selected_option_id": option_id, "level": found.bank.level}})
        if stored.get("status") == "duplicate":
            earlier = (stored.get("detail") or {})
            # Rows from before this engine hold no choice; they are only checked by question.
            if earlier.get("question_id") != found.question.id or earlier.get("selected_option_id") not in (None, option_id):
                raise PracticeError("This answer was already sent with another choice.", status_code=409,
                                    code="grammar_answer_conflict")
        return {"client_event_id": client_event_id, "exercise_id": found.question.id, "grammar_key": found.point.key,
                "correct": correct, "correct_option_id": found.question.correct_option_id,
                "explanation": found.question.explanation, "redo_closed": int(stored.get("requests_closed") or 0),
                "duplicate": stored.get("status") == "duplicate"}

    def lesson_learned(self, user_id: UUID, language: str, *, grammar_key: str, client_event_id: str) -> dict[str, Any]:
        found = find_point(self._banks(language, self._support(user_id)), grammar_key)
        if found is None or found[1].lesson is None:
            raise PracticeError("Unknown lesson.", status_code=404, code="grammar_lesson_unknown")
        stored = self.progress.record_lesson(user_id, language, grammar_key, f"grammar_lesson:{client_event_id}")
        return {"grammar_key": grammar_key, "lesson_learned_at": stored.get("lesson_learned_at")}


def _progress_view(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    attempts, correct = int(row.get("attempts") or 0), int(row.get("correct_count") or 0)
    return {"attempts": attempts, "correct_count": correct, "incorrect_count": attempts - correct,
            "lesson_learned_at": row.get("lesson_learned_at"), "last_correct_at": row.get("last_correct_at")}
