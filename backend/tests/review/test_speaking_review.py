from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.review.application.speaking_review import SpeakingReviewService
from app.modules.review.domain.models import FSRSState, initial_review_state
from app.modules.review.infrastructure.fsrs_adapter import FSRSAdapter
from tests.learning.test_l2_session_events import harness, output, sample

NOW = datetime(2026, 11, 7, 8, tzinfo=UTC)


def context(state=None, eligible=True):
    return {'occurred_at': NOW.isoformat(), 'review_state': state.model_dump(mode='json') if state else None,
            'eligible': eligible}


def test_independent_use_is_good_at_the_time_of_speech_and_never_an_attempt():
    store = Mock()
    store.context.return_value = context()
    store.commit.return_value = 'applied'
    session, user, concept = uuid4(), uuid4(), uuid4()
    SpeakingReviewService(store=store, adapter=FSRSAdapter()).apply(session, user, concept)
    identity = store.commit.call_args.args
    payload = identity[3]
    assert identity[:3] == (session, user, concept)
    assert payload['create'] is True
    assert payload['event']['rating'] == 3 and payload['event']['attempt_id'] is None
    assert payload['event']['provenance'] == 'speaking_use'
    assert payload['event']['reviewed_at'] == NOW.isoformat()
    assert payload['next']['reps'] == 1 and payload['next']['lapses'] == 0
    assert datetime.fromisoformat(payload['next']['due_at']) > NOW


def test_postgres_timestamps_in_a_non_utc_session_are_normalized_before_fsrs():
    store = Mock()
    incoming = context()
    incoming['occurred_at'] = NOW.astimezone(timezone(timedelta(hours=7))).isoformat()
    store.context.return_value = incoming
    store.commit.return_value = 'applied'
    SpeakingReviewService(store=store, adapter=FSRSAdapter()).apply(uuid4(), uuid4(), uuid4())
    payload = store.commit.call_args.args[3]
    assert datetime.fromisoformat(payload['next']['last_reviewed_at']) == NOW
    assert datetime.fromisoformat(payload['next']['due_at']) > NOW


@pytest.mark.parametrize('later', [0, 1])
def test_delayed_evidence_cannot_overwrite_a_more_recent_review(later):
    user, concept = uuid4(), uuid4()
    state = initial_review_state(user_id=user, concept_id=concept).model_copy(update={
        'state': FSRSState.REVIEW, 'reps': 2, 'last_reviewed_at': NOW + timedelta(seconds=later),
    })
    store, adapter = Mock(), Mock()
    store.context.return_value = context(state)
    store.commit.return_value = 'skipped'
    SpeakingReviewService(store=store, adapter=adapter).apply(uuid4(), user, concept)
    adapter.apply.assert_not_called()
    assert store.commit.call_args.args[3] is None


def test_paused_or_known_words_are_marked_skipped_without_changing_the_schedule():
    store, adapter = Mock(), Mock()
    store.context.return_value = context(eligible=False)
    store.commit.return_value = 'skipped'
    SpeakingReviewService(store=store, adapter=adapter).apply(uuid4(), uuid4(), uuid4())
    adapter.apply.assert_not_called()
    assert store.commit.call_args.args[3] is None


def test_an_already_projected_or_ineligible_event_never_writes_again():
    store, adapter = Mock(), Mock()
    store.context.return_value = None
    SpeakingReviewService(store=store, adapter=adapter).apply(uuid4(), uuid4(), uuid4())
    adapter.apply.assert_not_called()
    store.commit.assert_not_called()


def test_a_concurrent_review_is_reread_before_retrying():
    user, concept, session = uuid4(), uuid4(), uuid4()
    newer = initial_review_state(user_id=user, concept_id=concept).model_copy(update={
        'id': uuid4(), 'state': FSRSState.REVIEW, 'reps': 2, 'version': 2,
        'stability': 4, 'difficulty': 5, 'last_reviewed_at': NOW - timedelta(days=1),
    })
    store = Mock()
    store.context.side_effect = [context(), context(newer)]
    store.commit.side_effect = ['conflict', 'applied']
    SpeakingReviewService(store=store, adapter=FSRSAdapter()).apply(session, user, concept)
    payload = store.commit.call_args.args[3]
    assert payload['create'] is False and payload['previous']['version'] == 2
    assert payload['next']['reps'] == 3 and payload['next']['version'] == 3


@pytest.mark.parametrize('status', ['conflict', None, 'unexpected'])
def test_unconfirmed_commits_stay_pending_instead_of_being_reported_as_success(status):
    store = Mock()
    store.context.return_value = context()
    store.commit.return_value = status
    with pytest.raises(RuntimeError):
        SpeakingReviewService(store=store, adapter=FSRSAdapter()).apply(uuid4(), uuid4(), uuid4())
    assert store.commit.call_count == (3 if status == 'conflict' else 1)


@pytest.mark.parametrize('assisted', [False, True])
def test_learning_projects_both_kinds_to_rungs_but_only_independent_use_to_fsrs(assisted):
    from app.modules.learning.application.session_events import LearnerTurn
    from tests.learning.test_l2_session_events import WORD
    data = sample(turns=[LearnerTurn(text='I travel with my family.', assisted_ids=[WORD] if assisted else [])])
    service, _ = harness(data)
    service.model.generate_structured.return_value = output(data)
    service.reviews = Mock()
    service.submit(data)
    assert service.process(data.id)['status'] == 'completed'
    assert service.reviews.apply.call_count == (0 if assisted else 1)
    service.rungs.refresh_rung.assert_called_once()


def test_a_failed_review_projection_retries_without_sending_text_back_to_the_model():
    service, data = harness()
    service.reviews = Mock()
    service.reviews.apply.side_effect = [RuntimeError('database unavailable'), None]
    service.submit(data)
    assert service.process(data.id)['status'] == 'projection_pending'
    assert service.process(data.id)['status'] == 'completed'
    service.model.generate_structured.assert_called_once()
