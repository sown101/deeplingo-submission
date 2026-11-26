"""Progress (PRD 8.10, TARGET_DESIGN section 8): the numbers match the learner's log and review states, only their
own rows are read."""
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.progress import get_progress_service
from app.main import app
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.progress.application.service import ProgressError, ProgressService
from app.modules.progress.domain.models import (
    CardRow,
    LogRow,
    PronunciationRow,
    totals_from_rows,
)
from app.modules.progress.infrastructure.repositories import ProgressRepository

PREFIX = "/api/v1/v3"
USER = UUID("00000000-0000-0000-0000-00000000000a")
OTHER = UUID("00000000-0000-0000-0000-00000000000b")
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)


def at(days_ago: int, hour: int = 9) -> datetime:
    return (NOW - timedelta(days=days_ago)).replace(hour=hour)


def row(days_ago: int, kind: str = "flashcard", outcome: str = "correct", language: str = "en", **fields) -> LogRow:
    return LogRow(language_code=language, kind=kind, outcome=outcome, occurred_at=at(days_ago), **fields)


class Store:
    """The log and the cards of two learners; reads filter by learner and language like the real function, and the
    totals use the reference arithmetic that `v3.learner_progress_totals` reproduces in SQL."""

    def __init__(self, rows: dict[UUID, list[LogRow]], cards: dict[UUID, list[CardRow]] | None = None,
                 languages: dict[UUID, list[str]] | None = None, scores: dict[UUID, list[tuple[str, PronunciationRow]]] | None = None):
        self.rows, self.cards, self.langs, self.scores = rows, cards or {}, languages or {}, scores or {}

    def pronunciation_rows(self, *, user_id, language_code, since):
        return [r for code, r in self.scores.get(user_id, []) if language_code in (None, code) and r.occurred_at >= since]

    def log_rows(self, *, user_id, language_code, since):
        return [r for r in self.rows.get(user_id, []) if language_code in (None, r.language_code) and r.occurred_at >= since]

    def card_rows(self, *, user_id, language_code):
        return [c for c in self.cards.get(user_id, []) if language_code in (None, c.language_code)]

    def languages(self, *, user_id):
        return self.langs.get(user_id, [])

    def totals(self, *, user_id, language_code, now, utc_offset_minutes):
        since = now - timedelta(days=366)
        return totals_from_rows(self.log_rows(user_id=user_id, language_code=language_code, since=since),
                                self.card_rows(user_id=user_id, language_code=language_code),
                                self.pronunciation_rows(user_id=user_id, language_code=language_code, since=since),
                                now=now, utc_offset_minutes=utc_offset_minutes)


def service(store: Store) -> ProgressService:
    return ProgressService(store=store, clock=lambda: NOW)


def test_streak_counts_days_with_any_log_row_and_survives_a_gap():
    store = Store({USER: [row(0), row(0, "lookup", "done"), row(1), row(2), row(5), row(6), row(7), row(8)]})
    view = service(store).progress(USER, language=None)
    assert (view.streak.current, view.streak.longest, view.streak.active_days) == (3, 4, 7)
    assert [(day.date, day.count) for day in view.heatmap][-1] == (date(2026, 11, 14), 2)


def test_the_streak_survives_until_today_is_practised_and_ends_after_a_missed_day():
    assert service(Store({USER: [row(1), row(2)]})).progress(USER, language=None).streak.current == 2
    assert service(Store({USER: [row(2), row(3)]})).progress(USER, language=None).streak.current == 0


def test_the_offset_moves_a_late_utc_row_to_the_next_local_day():
    late = LogRow(language_code="en", kind="lookup", outcome="done", occurred_at=datetime(2026, 11, 13, 20, tzinfo=UTC))
    view = service(Store({USER: [late]})).progress(USER, language=None, utc_offset_minutes=420)
    assert [day.date for day in view.heatmap] == [date(2026, 11, 14)] and view.streak.current == 1


def test_rows_older_than_a_year_do_not_count():
    view = service(Store({USER: [row(400), row(10)]})).progress(USER, language=None)
    assert view.streak.active_days == 1 and len(view.heatmap) == 1


def test_the_language_filter_narrows_every_number():
    rows = [row(0, "flashcard", language="en"), row(0, "flashcard", "incorrect", language="zh"),
            row(1, "speaking_session", "done", language="zh", seconds=600)]
    cards = [CardRow("en", "review", at(-1)), CardRow("zh", "new", at(0))]
    store = Store({USER: rows}, {USER: cards}, {USER: ["en", "zh"]})
    everything = service(store).progress(USER, language=None)
    chinese = service(store).progress(USER, language="zh")
    assert everything.language is None and chinese.language == "zh"
    assert everything.languages == chinese.languages == ["en", "zh"]
    assert everything.streak.active_days == 2 and [d.language_code for d in everything.cards] == ["en", "zh"]
    assert chinese.accuracy[0].attempts == 1 and chinese.accuracy[0].correct == 0
    assert [d.language_code for d in chinese.cards] == ["zh"]
    assert chinese.speaking.sessions == 1 and chinese.speaking.minutes == 10.0


def test_accuracy_per_kind_counts_graded_rows_only():
    rows = [row(0, "choice"), row(0, "choice"), row(0, "choice", "incorrect"), row(0, "choice", "partial"),
            row(1, "cloze", "incorrect"), row(1, "lookup", "done"), row(1, "speaking_turn", "done")]
    view = service(Store({USER: rows})).progress(USER, language=None)
    assert [(a.kind, a.attempts, a.correct, a.accuracy) for a in view.accuracy] == [
        ("choice", 4, 2, 50.0), ("cloze", 1, 0, 0.0)]


def test_cards_by_fsrs_state_per_deck_with_the_due_ones():
    cards = [CardRow("en", "new", at(0)), CardRow("en", "learning", at(0)), CardRow("en", "review", at(-3)),
             CardRow("en", "review", at(2)), CardRow("en", "relearning", at(0)), CardRow("zh", "review", None)]
    view = service(Store({USER: []}, {USER: cards})).progress(USER, language=None)
    en, zh = view.cards
    assert (en.total, en.new, en.learning, en.review, en.relearning, en.due) == (5, 1, 1, 2, 1, 4)
    assert (zh.total, zh.review, zh.due) == (1, 1, 0)


def test_pronunciation_per_day_grammar_regions_and_speaking_minutes():
    rows = [row(0, "pronunciation", "correct"), row(0, "shadowing", "partial", source_type="video_region", source_id="r1"),
            row(1, "pronunciation", "correct"),
            row(2, "grammar_lesson", "done", item_type="grammar_point", item_id="g1"),
            row(2, "grammar_lesson", "done", item_type="grammar_point", item_id="g2"),
            row(2, "grammar_exercise", "incorrect", item_type="grammar_point", item_id="g1"),
            row(3, "grammar_exercise", "correct", item_type="grammar_point", item_id="g1"),
            row(3, "grammar_exercise", "correct", item_type="grammar_point", item_id="g1"),
            row(3, "dictation", "correct", source_type="video_region", source_id="r1"),
            row(3, "region_question", "correct", source_type="video_region", source_id="r2"),
            row(4, "speaking_session", "done", seconds=150), row(5, "speaking_session", "done", seconds=90),
            row(5, "speaking_session", "done")]
    view = service(Store({USER: rows})).progress(USER, language=None)
    assert (view.grammar.learned, view.grammar.done_correctly) == (2, 1)
    assert view.regions_completed == 2
    assert (view.speaking.sessions, view.speaking.minutes) == (3, 4.0)
    assert [(w.week_start, w.minutes) for w in view.speaking.weeks] == [(date(2026, 11, 9), 4.0)]


def score(days_ago: int, pronunciation: float, accuracy: float, fluency: float, completeness=None, prosody=None,
          weak=()) -> PronunciationRow:
    return PronunciationRow(at(days_ago), pronunciation, accuracy, fluency, completeness, prosody, tuple(weak))


def test_pronunciation_is_averaged_per_day_with_every_metric_and_the_weakest_words_are_ranked():
    scores = [("en", score(0, 80, 70, 90, 100, 60, ["water", "three"])), ("en", score(0, 60, 50, 70, None, None, ["water"])),
              ("zh", score(1, 90, 85, 95, 100, None, ["shui", "san"])), ("en", score(500, 10, 10, 10))]
    store = Store({USER: []}, scores={USER: scores, OTHER: [("en", score(0, 1, 1, 1, weak=["secret"]))]})
    view = service(store).progress(USER, language=None)
    assert [d.model_dump(mode="json") for d in view.pronunciation] == [
        {"date": "2026-11-13", "pronunciation": 90.0, "accuracy": 85.0, "fluency": 95.0, "completeness": 100.0, "prosody": None, "sessions": 1},
        {"date": "2026-11-14", "pronunciation": 70.0, "accuracy": 60.0, "fluency": 80.0, "completeness": 100.0, "prosody": 60.0, "sessions": 2}]
    assert view.weak_words == ["water", "san", "shui", "three"]
    english = service(store).progress(USER, language="en")
    assert [d.sessions for d in english.pronunciation] == [2] and english.weak_words == ["water", "three"]


def test_only_the_callers_rows_are_read():
    store = Store({USER: [row(0)], OTHER: [row(0), row(1), row(2)]}, {OTHER: [CardRow("en", "review", at(0))]})
    mine = service(store).progress(USER, language=None)
    assert mine.streak.active_days == 1 and mine.cards == []


def test_an_offset_out_of_range_is_refused():
    with pytest.raises(ProgressError):
        service(Store({})).progress(USER, language=None, utc_offset_minutes=15 * 60)


def test_a_language_with_data_but_no_preference_still_appears_in_the_filter():
    store = Store({USER: [row(0, language="fr")]}, languages={USER: ["en"]})
    assert service(store).progress(USER, language=None).languages == ["en", "fr"]


# --- HTTP -----------------------------------------------------------------------------------------

@pytest.fixture
def http():
    store = Store({USER: [row(0), row(1, language="zh")], OTHER: [row(0)] * 9}, languages={USER: ["en", "zh"]})
    app.dependency_overrides[get_progress_service] = lambda: service(store)
    try:
        client = TestClient(app)
        assert client.get(f"{PREFIX}/learner/me/progress").status_code == 401
        app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(id=USER)
        yield client
    finally:
        app.dependency_overrides.pop(get_progress_service, None)
        app.dependency_overrides.pop(require_authenticated_user, None)


def test_the_route_returns_the_callers_numbers_for_one_language(http):
    everything = http.get(f"{PREFIX}/learner/me/progress").json()
    assert everything["streak"]["active_days"] == 2 and everything["languages"] == ["en", "zh"]
    chinese = http.get(f"{PREFIX}/learner/me/progress", params={"language": "zh"}).json()
    assert chinese["language"] == "zh" and chinese["streak"]["active_days"] == 1
    assert chinese["heatmap"] == [{"date": "2026-11-13", "count": 1}]


def test_the_route_validates_its_filters(http):
    assert http.get(f"{PREFIX}/learner/me/progress", params={"language": "x"}).status_code == 422
    assert http.get(f"{PREFIX}/learner/me/progress", params={"utc_offset_minutes": 2000}).status_code == 422


# --- Repository ---------------------------------------------------------------------------------

class Client:
    """Records every call; answers the progress function with the JSON the database returns."""

    def __init__(self, totals, preferences):
        self.totals, self.preferences, self.calls = totals, preferences, []

    def schema(self, name):
        self.calls.append(("schema", (name,)))
        return self

    def rpc(self, name, params):
        self.calls.append(("rpc", (name, params)))
        return type("Call", (), {"execute": lambda _: type("Result", (), {"data": self.totals})()})()

    def table(self, name):
        self.calls.append(("table", (name,)))
        return self

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return record

    def execute(self):
        return type("Result", (), {"data": self.preferences})()


def test_the_repository_asks_the_database_for_the_callers_totals_in_one_call():
    data = {"days": [{"day": "2026-11-14", "count": 3}], "graded": [{"kind": "choice", "attempts": 4, "correct": 3}],
            "grammar_learned": 2, "grammar_correct": 1, "regions": 1, "speaking_sessions": 2, "speaking_seconds": 150,
            "weeks": [{"week": "2026-11-09", "seconds": 150}],
            "cards": [{"language_code": "en", "state": "review", "total": 2, "due": 1},
                      {"language_code": "en", "state": "new", "total": 1, "due": 0}],
            "scores": [{"day": "2026-11-14", "sessions": 2, "pronunciation_sum": 163, "pronunciation_count": 2,
                        "accuracy_sum": 70, "accuracy_count": 1, "fluency_sum": None, "fluency_count": 0}],
            "weak": [{"word": "water", "count": 2}], "languages": ["zh", "en"]}
    client = Client(data, [{"language_code": "zh"}, {"language_code": "en"}, {"language_code": "zh"}])
    service = ProgressService(store=ProgressRepository(client), clock=lambda: NOW)
    view = service.progress(USER, language="en", utc_offset_minutes=420)
    rpc = [args for name, args in client.calls if name == "rpc"]
    assert rpc == [("learner_progress_totals", {"p_user_id": str(USER), "p_language_code": "en",
                                                 "p_now": NOW.isoformat(), "p_utc_offset_minutes": 420})]
    assert ("eq", ("user_id", str(USER))) in client.calls and not [c for c in client.calls if c == ("range",)]
    assert view.languages == ["zh", "en"] and view.streak.active_days == 1
    assert (view.accuracy[0].kind, view.accuracy[0].accuracy) == ("choice", 75.0)
    assert (view.cards[0].total, view.cards[0].review, view.cards[0].new, view.cards[0].due) == (3, 2, 1, 1)
    assert (view.pronunciation[0].pronunciation, view.pronunciation[0].accuracy, view.pronunciation[0].fluency) == (
        81.5, 70.0, None)
    assert view.weak_words == ["water"] and view.speaking.minutes == 2.5 and view.regions_completed == 1
