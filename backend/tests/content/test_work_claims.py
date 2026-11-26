"""Local contract/model tests, deliberately NOT real PostgreSQL/process evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import re

import pytest
from pydantic import ValidationError

from app.platform.config import Settings
from app.modules.content.domain.work_claims import ContentClaim, StaleContentClaim
from app.modules.content.infrastructure.repositories.content_claims import (
    ClaimedConcepts,
    ClaimedLearningObjects,
    ClaimedTranscripts,
    ClaimedSegments,
    ClaimedRomanizations,
    ClaimedConceptLinks,
    fenced_rpc,
)
from app.modules.content.infrastructure.repositories.video_work_intents import (
    VideoWorkIntentRepository,
)
from app.bootstrap.wiring.content import (
    build_content_ingestion_service,
    build_learning_content_preparation_service,
)
from app.modules.content.worker import tasks as worker


MIGRATION = Path(__file__).resolve().parents[2] / 'supabase/migrations/20260930040000_content_worker_lease_fencing_v6b2c.sql'


def claim(stage='transcript', epoch=1):
    return ContentClaim(uuid4(), uuid4(), stage, 1, uuid4(), epoch,
                        datetime.now(UTC) + timedelta(seconds=2100))


class RpcClient:
    def __init__(self, data=None, error=None):
        self.data, self.error = data, error
        self.calls = []

    def schema(self, schema):
        assert schema == 'v3'
        return self

    def rpc(self, name, parameters):
        self.calls.append((name, parameters))
        return self

    def execute(self):
        if self.error:
            raise self.error
        return SimpleNamespace(data=self.data)


class RpcError(RuntimeError):
    def __init__(self, code):
        self.code = code


class LeaseModel:
    """Executable ownership specification with a simulated DB clock and lock."""
    def __init__(self, stage):
        self.lock = Lock()
        self.now = datetime(2026, 9, 30, tzinfo=UTC)
        self.base = claim(stage)
        self.current = None
        self.state, self.epoch, self.recoveries = 'pending', 0, 0
        self.canonical = None

    def acquire(self):
        with self.lock:
            if self.state != 'pending':
                return None
            self.epoch += 1
            self.current = replace(self.base, token=uuid4(), epoch=self.epoch,
                                   lease_expires_at=self.now + timedelta(seconds=10))
            self.state = 'running'
            return self.current

    def recover(self):
        with self.lock:
            if self.state != 'running' or self.current.lease_expires_at > self.now:
                return False
            self.current, self.state = None, 'pending'
            self.recoveries += 1
            return True

    def commit(self, owner, result, failure=False):
        with self.lock:
            if (self.state != 'running' or self.current != owner
                    or owner.lease_expires_at <= self.now):
                raise StaleContentClaim()
            self.state = 'failed' if failure else 'completed'
            self.canonical = result


@pytest.mark.parametrize('stage', ['transcript', 'learning_preparation'])
def test_concurrent_model_claim_has_one_owner(stage):
    model, barrier = LeaseModel(stage), Barrier(2)
    def acquire(_):
        barrier.wait(timeout=5)
        return model.acquire()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, range(2)))
    assert len([owner for owner in results if owner]) == 1
    assert model.epoch == 1
    assert model.acquire() is None  # duplicate broker delivery


@pytest.mark.parametrize('stage', ['transcript', 'learning_preparation'])
def test_model_expiry_reclaim_stale_success_and_failure(stage):
    model = LeaseModel(stage)
    a = model.acquire()
    assert model.recover() is False
    model.now += timedelta(seconds=10)
    with pytest.raises(StaleContentClaim):
        model.commit(a, 'A')  # even before recovery, expired A cannot write
    assert model.recover() is True
    assert model.recover() is False
    b = model.acquire()
    assert b.intent_id == a.intent_id and b.generation == a.generation
    assert b.token != a.token and b.epoch == a.epoch + 1
    model.commit(b, 'B')
    for failure in (False, True):
        with pytest.raises(StaleContentClaim):
            model.commit(a, 'A', failure)
    assert model.canonical == 'B' and model.state == 'completed'


@pytest.mark.parametrize('stage', ['transcript', 'learning_preparation'])
def test_two_model_recoverers_are_repeat_safe(stage):
    model, barrier = LeaseModel(stage), Barrier(2)
    model.acquire()
    model.now += timedelta(seconds=11)
    def recover(_):
        barrier.wait(timeout=5)
        return model.recover()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(recover, range(2))) == [False, True]
    assert model.recoveries == 1 and model.epoch == 1


def test_claim_adapter_deserializes_server_ownership():
    owner = claim()
    data = dict(id=str(owner.intent_id), video_id=str(owner.video_id), stage=owner.stage,
                generation=1, claim_token=str(owner.token), claim_epoch=1,
                lease_expires_at=owner.lease_expires_at.isoformat())
    client = RpcClient(data)
    assert VideoWorkIntentRepository(client).claim(owner.intent_id) == owner
    name, args = client.calls[0]
    assert name == 'claim_leased_content_work' and args['p_lease_seconds'] == 2100
    assert 'p_claim_token' not in args  # the DB generates the identity


def test_claim_adapter_none_and_missing_ownership_fail_closed():
    repo = VideoWorkIntentRepository(RpcClient())
    assert repo.claim(uuid4()) is None
    with pytest.raises(KeyError):
        VideoWorkIntentRepository(RpcClient(dict(id=str(uuid4())))).claim(uuid4())


@pytest.mark.parametrize('name', ['complete_claimed_transcript', 'complete_claimed_preparation',
                                'fail_claimed_content_work', 'enrich_claimed_occurrence',
                                'resolve_claimed_occurrence', 'resolve_claimed_concept',
                                'write_claimed_transcript_track', 'write_claimed_transcript_segments',
                                'write_claimed_segment_romanizations', 'link_claimed_concept_reference',
                                'record_claimed_sense_review'])
def test_fenced_adapter_sends_identity_and_propagates_staleness(name):
    owner, client = claim(), RpcClient(error=RpcError('DL001'))
    with pytest.raises(StaleContentClaim):
        fenced_rpc(client, name, owner)
    assert client.calls[0][1] == dict(p_intent_id=str(owner.intent_id),
                                    p_claim_token=str(owner.token), p_claim_epoch=owner.epoch)


def test_non_stale_database_error_is_not_misclassified():
    with pytest.raises(RpcError):
        fenced_rpc(RpcClient(error=RpcError('40001')), 'complete_claimed_transcript', claim())


def test_enrichment_adapter_never_sends_old_jsonb_snapshot():
    client, owner = RpcClient(error=RpcError('DL001')), claim('learning_preparation')
    new = {'target_language_code': 'vi', 'contextual_meaning': 'new'}
    with pytest.raises(StaleContentClaim):
        ClaimedLearningObjects(client, owner).update_enrichment(uuid4(), {
            'raw_ai_diagnostics': {'enrichment': new, 'enrichments': {'fr': {'old': True}}},
        })
    args = client.calls[0][1]
    assert args['p_enrichment'] == new
    assert 'raw_ai_diagnostics' not in args


def test_sense_review_adapter_sends_only_the_language_and_review():
    client, owner = RpcClient(error=RpcError('DL001')), claim('learning_preparation')
    review = {'status': 'no_matching_sense', 'concept_id': str(uuid4()), 'offered_sense_ids': ['enwikt:1']}
    with pytest.raises(StaleContentClaim):
        ClaimedLearningObjects(client, owner).record_sense_review(
            uuid4(), target_language_code='vi', review=review,
            raw_ai_diagnostics={'enrichments': {'fr': {'old': True}}, 'dictionary_review': {'vi': review}})
    name, args = client.calls[0]
    assert name == 'record_claimed_sense_review'
    assert args['p_target_language_code'] == 'vi' and args['p_review'] == review
    assert not any('diagnostics' in key for key in args)


@pytest.mark.parametrize('limit', [0, 101, -1])
def test_recovery_adapter_rejects_unbounded_scans(limit):
    with pytest.raises(ValueError):
        VideoWorkIntentRepository(RpcClient()).recover_expired(limit=limit)


def test_recovery_adapter_uses_rpc_database_clock():
    client = RpcClient(2)
    assert VideoWorkIntentRepository(client).recover_expired(limit=50) == 2
    assert client.calls == [('recover_expired_content_work', {'p_limit': 50})]


def test_factories_scope_all_async_mutable_repositories(monkeypatch):
    # Building the services must not need a live AI provider.
    monkeypatch.setattr("app.bootstrap.wiring.content.OpenAICompatibleLLMProvider", Mock)
    monkeypatch.setattr("app.bootstrap.wiring.content.OpenAICompatibleLearningObjectEnrichmentProvider", Mock)
    client = Mock()
    transcript = build_content_ingestion_service(client, claim=claim())
    assert isinstance(transcript.transcripts, ClaimedTranscripts)
    assert isinstance(transcript.segments, ClaimedSegments)
    assert isinstance(transcript.romanizations, ClaimedRomanizations)
    prep = build_learning_content_preparation_service(client, claim=claim('learning_preparation'))
    assert isinstance(prep.learning_objects, ClaimedLearningObjects)
    assert isinstance(prep.resolution.resolution.concept_resolver.concepts, ClaimedConcepts)
    assert isinstance(prep.resolution.resolution.concept_dictionary_links, ClaimedConceptLinks)
    with pytest.raises(RuntimeError):
        prep.resolution.resolution.dictionary_resolver.entries.upsert_by_lookup({})


def test_short_lease_requires_explicit_development_proof_and_safe_default():
    default = Settings(_env_file=None, ENVIRONMENT='test', AI_PROVIDER='fake')
    assert default.CONTENT_WORK_LEASE_SECONDS == 2100
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENVIRONMENT='test', AI_PROVIDER='fake', CONTENT_WORK_LEASE_SECONDS=10)
    proof = Settings(_env_file=None, ENVIRONMENT='test', AI_PROVIDER='fake',
                     CONTENT_WORK_LEASE_SECONDS=10, CONTENT_WORK_SHORT_LEASE_PROOF=True)
    assert proof.CONTENT_WORK_LEASE_SECONDS == 10
    with pytest.raises(ValidationError, match='development/test-only'):
        Settings(_env_file=None, ENVIRONMENT='production', CONTENT_WORK_SHORT_LEASE_PROOF=True)


@pytest.mark.parametrize('stage', ['transcript', 'learning_preparation'])
@pytest.mark.parametrize('error', ['stale', 'failure'])
def test_worker_stale_compute_or_failure_cannot_persist(monkeypatch, stage, error):
    owner = claim(stage)
    intents = Mock()
    intents.get.return_value = SimpleNamespace(stage=stage)
    intents.claim.return_value = owner
    intents.record_failure.side_effect = StaleContentClaim()
    service = Mock()
    service.process_video.side_effect = StaleContentClaim() if error == 'stale' else RuntimeError()
    service.prepare_claimed.side_effect = StaleContentClaim() if error == 'stale' else RuntimeError()
    monkeypatch.setattr(worker, 'supabase_service', object())
    monkeypatch.setattr(worker, 'build_work_intents', lambda _: intents)
    monkeypatch.setattr(worker, 'build_content_ingestion_service', lambda _, **kwargs: service)
    monkeypatch.setattr(worker, 'build_learning_content_preparation_service', lambda _, **kwargs: service)
    task = worker.process_prepared_video_v3 if stage == 'transcript' else worker.prepare_video_learning_content
    assert task.run(str(owner.intent_id))['status'] == 'stale_claim'
    intents.finish_preparation.assert_not_called()
    service.videos.update_status.assert_not_called()
    service.videos.finish_learning_preparation.assert_not_called()
    if error == 'stale':
        intents.record_failure.assert_not_called()


def test_beat_recovers_before_existing_dispatch(monkeypatch):
    calls = []
    intents = SimpleNamespace(recover_expired=lambda **kwargs: calls.append(('recover', kwargs)) or 2)
    dispatcher = SimpleNamespace(reconcile_due=lambda **kwargs: calls.append(('dispatch', kwargs)) or (2, 2))
    monkeypatch.setattr(worker, 'supabase_service', object())
    monkeypatch.setattr(worker, 'build_work_intents', lambda _: intents)
    monkeypatch.setattr(worker, 'ContentWorkDispatcher', lambda _: dispatcher)
    assert worker.reconcile_content_work_intents.run() == {'recovered': 2, 'scanned': 2, 'dispatched': 2}
    assert calls == [('recover', {'limit': 50}), ('dispatch', {'limit': 50})]


def test_explicit_task_limits_and_ack_policy_unchanged():
    for task in (worker.process_prepared_video_v3, worker.prepare_video_learning_content):
        assert task.time_limit == 1800 and task.soft_time_limit == 1500
        assert task.acks_late is False


def test_stale_preparation_terminal_rpc_does_not_attempt_failure(monkeypatch):
    owner = claim('learning_preparation')
    intents = Mock()
    intents.get.return_value = SimpleNamespace(stage=owner.stage)
    intents.claim.return_value = owner
    intents.finish_preparation.side_effect = StaleContentClaim()
    service = Mock(support_language_code='vi')
    service.prepare_claimed.return_value = SimpleNamespace(status='ready', usable_count=1, failure_code=None)
    monkeypatch.setattr(worker, 'supabase_service', object())
    monkeypatch.setattr(worker, 'build_work_intents', lambda _: intents)
    monkeypatch.setattr(worker, 'build_learning_content_preparation_service', lambda _, **kwargs: service)
    assert worker.prepare_video_learning_content.run(str(owner.intent_id))['status'] == 'stale_claim'
    intents.record_failure.assert_not_called()
    service.prepare_claimed.assert_called_once_with(owner.video_id, persist_terminal=False)


def test_internal_retry_is_durably_scheduled_without_celery_counter_authority():
    owner, intents = claim(), Mock()
    from app.modules.content.domain.failures import ContentFailure, ContentFailureClass
    intents.record_failure.return_value = 'pending'
    failure = ContentFailure(ContentFailureClass.TRANSIENT, 'transient_network', True)
    assert worker._failure(intents, owner, failure=failure)['status'] == 'retry_scheduled'
    intents.record_failure.assert_called_once_with(owner, failure_code='transient_network',
        failure_class='transient', explicit_retry=True)


@pytest.mark.parametrize('changes', [{'epoch': 0}, {'generation': 0}, {'stage': 'speech'},
                                    {'lease_expires_at': datetime(2026, 9, 30)}])
def test_invalid_claim_value_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(claim(), **changes)


def test_migration_private_grants_and_each_mutation_fenced():
    sql = MIGRATION.read_text(encoding='utf-8')
    functions = re.findall(r'create (?:or replace )?function v3\.(\w+)\([^$]+?as \$\$(.*?)\$\$;', sql, re.S)
    assert len(functions) == 16
    for name, body in functions:
        assert f'revoke all on function v3.{name}(' in sql
        if name.startswith(('write_claimed_', 'resolve_claimed_', 'enrich_claimed_', 'complete_claimed_', 'fail_claimed_', 'link_claimed_')):
            assert 'lock_current_content_claim(' in body
        if name in {'claim_video_content_work', 'complete_transcript_content_work', 'reset_failed_video_content_work'}:
            assert "raise exception" in body and "DL001" in body
            assert 'service_role;' in sql.split(f'revoke all on function v3.{name}(')[1].split('\n')[0]
    assert sql.count("security invoker set search_path = ''") == len(functions)
    assert 'security definer' not in sql
    assert not re.search(r'^grant all\b', sql, re.M | re.I)
    assert 'claim_epoch = claim_epoch + 1' in sql and 'clock_timestamp()' in sql
    assert 'for update skip locked' in sql and 'limit p_limit' in sql
    assert 'lease_expires_at is not null' in sql
    assert "requires a drained running-intent cutover" in sql
    assert "or (i.state = 'pending' and i.next_dispatch_at > ts)" in sql
    assert "diag || jsonb_build_object('enrichments', langs" in sql
    assert 'claim_token = null' in sql and 'recovery_count = recovery_count + 1' in sql
    assert 'delete from' not in sql.casefold()
