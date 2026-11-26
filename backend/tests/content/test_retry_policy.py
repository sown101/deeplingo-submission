"""Local executable policy/model and adapter tests; NOT hosted SQL/process proof."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.bootstrap.worker import celery_app
from app.modules.content.domain.work_claims import ContentClaim
from app.modules.content.domain.failures import (
    ContentFailure,
    ContentFailureClass as C,
)
from app.modules.content.application.library import LearnerLibraryError, LearnerLibraryService
from app.modules.content.application.ingestion import ContentIngestionError
from app.modules.content.domain.library import ContentProcessingFailureCode
from app.modules.content.application.store_ports import ContentWorkBackpressure
from app.modules.content.infrastructure.repositories.video_work_intents import (
    VideoWorkIntentRepository,
)
from app.modules.content.worker.failure_classification import classify_content_failure
from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory as P
from app.modules.content.application.candidate_extraction import CandidateExtractionService
from app.modules.content.worker import tasks as worker



def claim(stage='transcript', epoch=1):
    return ContentClaim(uuid4(), uuid4(), stage, 1, uuid4(), epoch,
                        datetime.now(UTC) + timedelta(seconds=2100))


@pytest.mark.parametrize('error,category,code', [
    (TimeoutError('private source'), C.TRANSIENT, 'transient_timeout'),
    (ConnectionError('private endpoint'), C.TRANSIENT, 'transient_network'),
    (LLMProviderError('secret', http_status=429), C.TRANSIENT, 'provider_rate_limit'),
    (LLMProviderError('secret', http_status=503), C.TRANSIENT, 'provider_temporary'),
    (LLMProviderError('secret', http_status=401), C.PERMANENT, 'configuration_error'),
    (LLMProviderError('secret', category=P.CONFIGURATION), C.PERMANENT, 'configuration_error'),
    (LLMProviderError('secret', category=P.SCHEMA_VIOLATION), C.PERMANENT, 'validation_failed'),
    (LLMProviderError('secret', category=P.REFUSAL), C.PERMANENT, 'validation_failed'),
    (ValueError('trusted context absent'), C.PERMANENT, 'validation_failed'),
    (RuntimeError('unexpected bug'), C.UNKNOWN, 'unknown_failure'),
    (ContentIngestionError(ContentProcessingFailureCode.VIDEO_UNAVAILABLE,
         retryable=False, status_code=422), C.PERMANENT, 'content_unavailable'),
])
def test_explicit_taxonomy_never_retains_exception_body(error, category, code):
    result = classify_content_failure(error)
    assert (result.category, result.code) == (category, code)
    assert 'secret' not in repr(result) and 'private' not in repr(result)


def test_original_typed_cause_survives_coarse_ingestion_wrapper():
    wrapped = ContentIngestionError(ContentProcessingFailureCode.PROCESSING_FAILED,
                                   retryable=True, status_code=503)
    wrapped.__cause__ = TimeoutError()
    assert classify_content_failure(wrapped).code == 'transient_timeout'
    wrapped.__cause__ = RuntimeError('not evidence of temporary failure')
    assert classify_content_failure(wrapped).category == C.UNKNOWN


def test_provider_adapter_unknown_wrapping_not_blindly_transient():
    wrapped = LLMProviderError('safe')
    wrapped.__cause__ = RuntimeError('bug')
    assert classify_content_failure(wrapped).category == C.UNKNOWN


@pytest.mark.parametrize('sqlstate,category', [('40001', C.TRANSIENT), ('PGRST003', C.TRANSIENT),
    ('42501', C.PERMANENT), ('23514', C.PERMANENT), ('PGRST202', C.PERMANENT), ('unexpected', C.UNKNOWN)])
def test_database_error_taxonomy(sqlstate, category):
    error = RuntimeError('raw details never retained')
    error.code = sqlstate
    assert classify_content_failure(error).category == category


def test_implicit_source_exception_context_is_preserved():
    from app.modules.content.application.ports import SourceProviderError
    from requests.exceptions import Timeout
    wrapper = SourceProviderError('legacy coarse transport')
    wrapper.__context__ = Timeout('secret')
    assert classify_content_failure(wrapper).code == 'transient_timeout'


def test_claim_unknown_outcome_cannot_write_failure_without_token():
    intents = Mock()
    intents.get.return_value = SimpleNamespace(stage='transcript')
    intents.claim.side_effect = TimeoutError()
    assert worker._claim(intents, uuid4(), 'transcript') is None
    intents.record_failure.assert_not_called()


@pytest.mark.parametrize('stage', ['transcript', 'learning_preparation'])
@pytest.mark.parametrize('error,status,category', [
    (TimeoutError(), 'retry_scheduled', 'transient'),
    (ValueError(), 'failed', 'permanent'),
    (RuntimeError(), 'failed', 'unknown'),
])
def test_actual_worker_calls_new_fenced_failure_boundary(monkeypatch, stage, error, status, category):
    owner, intents = claim(stage), Mock()
    intents.get.return_value = SimpleNamespace(stage=stage)
    intents.claim.return_value = owner
    intents.record_failure.return_value = 'pending' if status == 'retry_scheduled' else 'failed'
    service = Mock()
    service.process_video.side_effect = error
    service.prepare_claimed.side_effect = error
    monkeypatch.setattr(worker, 'supabase_service', object())
    monkeypatch.setattr(worker, 'build_work_intents', lambda _: intents)
    monkeypatch.setattr(worker, 'build_content_ingestion_service', lambda *args, **kwargs: service)
    monkeypatch.setattr(worker, 'build_learning_content_preparation_service', lambda *args, **kwargs: service)
    task = worker.process_prepared_video_v3 if stage == 'transcript' else worker.prepare_video_learning_content
    with pytest.MonkeyPatch.context() as patch:
        retry = Mock(side_effect=AssertionError('Celery must not own execution budget'))
        patch.setattr(task, 'retry', retry)
        assert task.run(str(owner.intent_id))['status'] == status
        retry.assert_not_called()
    assert intents.record_failure.call_args.kwargs['failure_class'] == category
    assert intents.record_failure.call_args.args == (owner,)
    intents.fail_claim.assert_not_called()


def test_failure_commit_unknown_never_writes_unfenced_or_blind_retries():
    intents = Mock()
    intents.record_failure.side_effect = ConnectionError()
    assert worker._failure(intents, claim(), failure=ContentFailure(C.TRANSIENT, 'transient_network', True))['status'] == 'failure_reconciliation_pending'
    assert intents.record_failure.call_count == 1
    intents.fail_claim.assert_not_called()


def test_failure_record_adapter_preserves_current_claim_without_delay_authority():
    calls = []
    class RpcClient:
        def schema(self, schema):
            assert schema == 'v3'
            return self
        def rpc(self, name, payload):
            calls.append((name, payload))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data='pending'))
    owner = claim()
    assert VideoWorkIntentRepository(RpcClient()).record_failure(owner,
        failure_code='provider_rate_limit', failure_class='transient', explicit_retry=True) == 'pending'
    name, payload = calls[0]
    assert name == 'record_content_work_failure'
    assert payload['p_claim_epoch'] == owner.epoch and payload['p_claim_token'] == str(owner.token)
    assert 'p_retry_delay' not in payload and 'generation' not in payload


def test_admission_pressure_maps_to_safe_http_error_and_no_publish():
    service = LearnerLibraryService(library=Mock(), videos=Mock(), transcripts=Mock(),
        ingestion=Mock(), work_intents=Mock(), dispatcher=Mock(), import_budget=Mock())
    service.work_intents.admit.side_effect = ContentWorkBackpressure()
    with pytest.raises(LearnerLibraryError) as exc:
        service._admit(user_id=uuid4(), video_id=uuid4(), action='import')
    assert (exc.value.status_code, exc.value.code) == (503, 'content_backlog_full')
    service.dispatcher.dispatch.assert_not_called()


def test_async_extraction_propagates_typed_failure_without_inner_retry():
    provider = Mock(provider_name='fixture')
    provider.generate_structured.side_effect = LLMProviderError('safe', http_status=429)
    extraction = CandidateExtractionService(provider=provider, max_retries=0, propagate_failures=True)
    with pytest.raises(LLMProviderError):
        extraction.extract_segment(segment=SimpleNamespace(id=uuid4(), text='trusted source'), source_language='en')
    assert provider.generate_structured.call_count == 1


def test_time_prefetch_and_queue_defaults_are_bounded_without_new_queue():
    assert celery_app.conf.worker_concurrency == 2
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert not celery_app.conf.task_routes
    for task in (worker.process_prepared_video_v3, worker.prepare_video_learning_content):
        assert task.max_retries == 0 and not getattr(task, 'autoretry_for', ())
        assert (task.soft_time_limit, task.time_limit, task.acks_late) == (1500, 1800, False)

