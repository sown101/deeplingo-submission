"""FR-3.10: the "end of day" greeting. Home shows a plain line about yesterday's speaking: how many sessions,
how long, and which words to use again. It is built from counts and word names only (never what the learner
said), by the server from the speaking_session rows of the learning log."""
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock


from app.modules.learning.application.study_plan import YesterdaySpeaking, summarize_yesterday
from app.modules.learning.infrastructure.speaking_activity import SpeakingSessions
from tests.activity.fakes import make_activity
from tests.learning.test_companion import OWNER
from tests.learning.test_study_plan import TODAY, USER, make_service

NOW = datetime(2026, 10, 29, 3, 0, tzinfo=UTC)


def row(when, seconds=120, turns=3, words=()):
    return {"occurred_at": when.isoformat(), "seconds": seconds, "turns": turns, "reuse_words": list(words)}


def test_only_yesterdays_sessions_count_in_the_learners_own_day():
    # UTC+7: local yesterday (the 16th) runs from 2026-10-15T17:00Z to 2026-10-16T17:00Z.
    rows = [row(datetime(2026, 10, 15, 18, tzinfo=UTC), 300, 5, ["fly"]),
            row(datetime(2026, 10, 16, 16, tzinfo=UTC), 90, 2, ["airport", "fly"]),
            row(datetime(2026, 10, 16, 18, tzinfo=UTC), 600, 9, ["x"]),   # already the 17th locally
            row(datetime(2026, 10, 15, 16, tzinfo=UTC), 600, 9, ["y"])]   # still the 15th locally
    found = summarize_yesterday(rows, today=date(2026, 10, 17), utc_offset_minutes=420)
    assert found == YesterdaySpeaking(sessions=2, minutes=7, turns=7, reuse_words=["fly", "airport"])


def test_no_session_yesterday_means_no_greeting():
    assert summarize_yesterday([], today=date(2026, 10, 17), utc_offset_minutes=0) is None
    assert summarize_yesterday([row(datetime(2026, 10, 17, 9, tzinfo=UTC))], today=date(2026, 10, 17),
                               utc_offset_minutes=0) is None


def test_words_are_short_unique_and_at_most_six_and_nothing_else_is_kept():
    many = [f"w{n}" for n in range(9)]
    found = summarize_yesterday([row(datetime(2026, 10, 16, 9, tzinfo=UTC), words=[*many, "w0", "x" * 90, 5, ""])],
                                today=date(2026, 10, 17), utc_offset_minutes=0)
    assert found.reuse_words == many[:6]
    assert set(found.model_dump()) == {"sessions", "minutes", "turns", "reuse_words"}


def test_the_plan_carries_yesterdays_line_and_a_stored_plan_still_is_not_recomposed():
    service = make_service()
    service.speaking = Mock()
    service.speaking.rows_between.return_value = [row(datetime(2026, 10, 16, 9, tzinfo=UTC), 125, 4, ["fly"])]
    plan = service.today(USER, TODAY, utc_offset_minutes=0)
    assert plan.yesterday.sessions == 1 and plan.yesterday.minutes == 3 and plan.yesterday.reuse_words == ["fly"]
    window = service.speaking.rows_between.call_args
    assert window.args[0] == USER.id and window.args[2] - window.args[1] == timedelta(days=1)
    assert window.kwargs["language_code"] == plan.language_code  # the plan's language
    service.reviews.ready_count.reset_mock()
    assert service.today(USER, TODAY).plan_id == plan.plan_id
    service.reviews.ready_count.assert_not_called()


def test_without_a_reader_or_when_it_fails_the_plan_simply_has_no_greeting():
    assert make_service().today(USER, TODAY).yesterday is None
    service = make_service()
    service.speaking = Mock()
    service.speaking.rows_between.side_effect = RuntimeError("table missing")
    assert service.today(USER, TODAY).yesterday is None


def test_the_reader_takes_speaking_sessions_from_the_learning_log_in_the_window():
    from app.modules.activity.contracts import log_activity
    activity, _, _, _ = make_activity()
    start = datetime(2026, 11, 14, tzinfo=UTC)
    for minutes, kind in ((30, "speaking_session"), (60, "shadowing"), (60 * 30, "speaking_session")):
        log_activity(activity, user_id=OWNER, language_code="en", client_event_id=f"{kind}:{minutes}", kind=kind,
                     outcome="done", detail={"seconds": 61, "turns": 2, "reuse_words": ["fly"]},
                     occurred_at=start + timedelta(minutes=minutes))
    found = SpeakingSessions(activity).rows_between(OWNER, start, start + timedelta(days=1), language_code="en")
    assert found == [{"occurred_at": (start + timedelta(minutes=30)).isoformat(), "seconds": 61, "turns": 2,
                      "reuse_words": ["fly"]}]  # not shadowing, not the next day
    assert SpeakingSessions(activity).rows_between(OWNER, start, start + timedelta(days=1), language_code="zh") == []


def test_a_conversation_logs_how_many_turns_and_which_words_to_reuse_and_nothing_else():
    from tests.learning.test_speaking_activity import entries, run_conversation
    log = Mock()
    run_conversation(turns=["I like to fly.", "Every summer."], log=log)
    [row] = entries(log, "speaking_session")
    assert row.detail["turns"] == 2 and row.detail["reuse_words"] == []
    assert "fly" not in str(row.detail)
