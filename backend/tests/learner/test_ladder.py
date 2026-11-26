"""The usage ladder (L1a): every rung change is explained by events and replay agrees."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.modules.learner.domain.ladder import (
    EventKind,
    LadderState,
    Outcome,
    TargetEvent,
    apply_event,
    replay,
    rung_from_events,
)

UTC_TZ = ZoneInfo("UTC")
HCM = ZoneInfo("Asia/Ho_Chi_Minh")
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def event(kind, outcome=Outcome.CORRECT, *, days=0.0, context=None, at=None):
    return TargetEvent(kind=kind, outcome=outcome, occurred_at=at or T0 + timedelta(days=days), context_key=context)


def rung(*events, tz=UTC_TZ):
    return rung_from_events(list(events), tz)


def test_a_target_with_no_events_is_at_r0_and_seen_does_not_move_it():
    assert rung() == 0
    assert rung(event(EventKind.SEEN)) == 0


@pytest.mark.parametrize("kind, expected", [
    (EventKind.RECOGNITION, 1), (EventKind.RECALL, 2), (EventKind.FRAMED_USE, 3), (EventKind.SPONTANEOUS_USE, 4),
])
def test_a_correct_event_reaches_its_rung_directly(kind, expected):
    assert rung(event(kind)) == expected


def test_a_lower_correct_event_never_lowers_the_rung():
    assert rung(event(EventKind.SPONTANEOUS_USE), event(EventKind.RECOGNITION, days=1)) == 4


def test_two_consecutive_misses_step_down_one_rung_and_a_correct_event_resets_the_count():
    two_misses = [event(EventKind.SPONTANEOUS_USE), event(EventKind.SPONTANEOUS_USE, Outcome.INCORRECT, days=1),
                  event(EventKind.SPONTANEOUS_USE, Outcome.INCORRECT, days=2)]
    assert rung(*two_misses) == 3
    separated = [two_misses[0], two_misses[1], event(EventKind.RECOGNITION, days=1.5), two_misses[2]]
    assert rung(*separated) == 4


def test_a_miss_on_a_lower_kind_counts_toward_stepping_down():
    events = [event(EventKind.RECALL), event(EventKind.RECOGNITION, Outcome.INCORRECT, days=1),
              event(EventKind.RECOGNITION, Outcome.INCORRECT, days=2)]
    assert rung(*events) == 1


def test_a_failed_attempt_above_the_rung_changes_nothing():
    assert rung(event(EventKind.RECOGNITION), event(EventKind.SPONTANEOUS_USE, Outcome.INCORRECT, days=1)) == 1
    assert rung(event(EventKind.SPONTANEOUS_USE, Outcome.INCORRECT)) == 0


def test_the_rung_never_drops_below_r0():
    events = [event(EventKind.RECOGNITION), event(EventKind.RECOGNITION, Outcome.INCORRECT, days=1),
              event(EventKind.RECOGNITION, Outcome.INCORRECT, days=2),
              event(EventKind.RECOGNITION, Outcome.INCORRECT, days=3),
              event(EventKind.RECOGNITION, Outcome.INCORRECT, days=4)]
    assert rung(*events) == 0


def test_r5_needs_correct_spontaneous_use_on_two_days_at_least_three_days_apart():
    assert rung(event(EventKind.SPONTANEOUS_USE), event(EventKind.SPONTANEOUS_USE, days=2)) == 4
    assert rung(event(EventKind.SPONTANEOUS_USE), event(EventKind.SPONTANEOUS_USE, days=3)) == 5


def test_r5_needs_two_different_contexts_when_both_are_known():
    same = [event(EventKind.SPONTANEOUS_USE, context="travel"), event(EventKind.SPONTANEOUS_USE, days=5, context="travel")]
    different = [event(EventKind.SPONTANEOUS_USE, context="travel"),
                 event(EventKind.SPONTANEOUS_USE, days=5, context="work")]
    unknown = [event(EventKind.SPONTANEOUS_USE, context="travel"), event(EventKind.SPONTANEOUS_USE, days=5)]
    assert (rung(*same), rung(*different), rung(*unknown)) == (4, 5, 5)


def test_one_incorrect_spontaneous_use_ends_r5_and_the_two_day_proof_starts_over():
    reached = [event(EventKind.SPONTANEOUS_USE), event(EventKind.SPONTANEOUS_USE, days=4)]
    lost = [*reached, event(EventKind.SPONTANEOUS_USE, Outcome.INCORRECT, days=5)]
    assert rung(*reached) == 5 and rung(*lost) == 4
    again_one_day = [*lost, event(EventKind.SPONTANEOUS_USE, days=6)]
    assert rung(*again_one_day) == 4
    again_proved = [*lost, event(EventKind.SPONTANEOUS_USE, days=6), event(EventKind.SPONTANEOUS_USE, days=9)]
    assert rung(*again_proved) == 5


def test_days_are_counted_in_the_learners_local_time():
    first = event(EventKind.SPONTANEOUS_USE, at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC))  # 02 Oct 01:00 in HCM
    second = event(EventKind.SPONTANEOUS_USE, at=datetime(2026, 10, 4, 10, 0, tzinfo=UTC))  # 04 Oct 17:00 in HCM
    assert rung(first, second, tz=UTC_TZ) == 5
    assert rung(first, second, tz=HCM) == 4


def test_replay_ignores_input_order_and_equals_stepwise_application():
    events = [event(EventKind.SPONTANEOUS_USE, days=4), event(EventKind.RECOGNITION),
              event(EventKind.SPONTANEOUS_USE, days=1), event(EventKind.RECALL, Outcome.INCORRECT, days=2)]
    stepwise = LadderState()
    for item in sorted(events, key=lambda e: e.occurred_at):
        stepwise = apply_event(stepwise, item, UTC_TZ)
    assert replay(events, UTC_TZ) == stepwise
    assert replay(list(reversed(events)), UTC_TZ) == stepwise
