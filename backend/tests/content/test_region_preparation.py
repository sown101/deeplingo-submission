"""M1 S2: learning preparation per study region (service, claim, admission view, worker, SQL)."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.content.application.enrichment import DictionarySenseMismatch, LearningObjectEnrichmentError
from app.modules.content.application.region_preparation import (
    REGION_PREPARATION_VERSION,
    RegionPreparationService,
)
from app.modules.content.application.workspace import (
    RegionPreparationPolicy,
    StudyRegionRequest,
    VideoWorkspaceService,
)
from app.modules.content.domain.catalog import TranscriptSegment, Video, VideoTranscript
from app.modules.content.domain.knowledge import LearningObject
from app.modules.content.domain.region_preparation import (
    RegionAdmission,
    RegionPreparation,
    RegionPreparationStatus,
    covered_sequences,
)
from app.modules.content.domain.work_claims import ContentClaim
from app.modules.content.domain.workspace import LearnerVideoWorkspace
from app.modules.content.worker import dispatch as dispatch_module
from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory
from app.modules.content.worker import tasks as worker

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20261019120000_region_preparation_m1s2.sql"

VIDEO_ID, TRANSCRIPT_ID, CONCEPT_A, CONCEPT_B = uuid4(), uuid4(), uuid4(), uuid4()
SEGMENTS = [TranscriptSegment(id=uuid4(), transcript_id=TRANSCRIPT_ID, sequence_number=i,
                              start_ms=i * 4000, end_ms=(i + 1) * 4000, text=f"ended up at segment {i}")
            for i in range(1, 11)]


def region(start=5, end=7, *, status=RegionPreparationStatus.PROCESSING, **changes):
    values = dict(
        id=uuid4(), video_id=VIDEO_ID, transcript_id=TRANSCRIPT_ID,
        start_segment_id=SEGMENTS[start - 1].id, end_segment_id=SEGMENTS[end - 1].id,
        start_sequence=start, end_sequence=end, support_language_code="vi",
        preparation_version=REGION_PREPARATION_VERSION, status=status,
    )
    values.update(changes)
    return RegionPreparation(**values)


def claim_for(row, *, stage="region_preparation"):
    return ContentClaim(intent_id=uuid4(), video_id=VIDEO_ID, stage=stage, generation=1, token=uuid4(), epoch=1,
                        lease_expires_at=datetime.now(UTC) + timedelta(minutes=30),
                        region_preparation_id=row.id if stage == "region_preparation" else None)


def occurrence(sequence, *, concept=CONCEPT_A):
    segment = SEGMENTS[sequence - 1]
    return LearningObject(id=uuid4(), concept_id=concept, video_id=VIDEO_ID, transcript_segment_id=segment.id,
                          occurrence_index=1, evidence_text="ended up", start_codepoint=0, end_codepoint=8,
                          start_ms=segment.start_ms, end_ms=segment.end_ms)


class Regions:
    def __init__(self, *rows):
        self.rows = {row.id: row for row in rows}

    def get_by_id(self, region_id):
        return self.rows.get(region_id)

    def list_for_transcript(self, *, transcript_id, support_language_code, preparation_version):
        return [row for row in self.rows.values() if row.transcript_id == transcript_id
                and row.support_language_code == support_language_code
                and row.preparation_version == preparation_version]


class Resolution:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def extract_and_resolve_by_segment_id(self, segment_id, **context):
        self.calls.append((segment_id, context))
        objects = self.results.get(segment_id, [])
        return SimpleNamespace(resolved=[SimpleNamespace(learning_object=row) for row in objects], errors=[])


class Enrichment:
    def __init__(self, raises=None):
        self.raises = raises or {}
        self.calls = []

    def enrich(self, object_id, *, target_language_code):
        self.calls.append((object_id, target_language_code))
        if object_id in self.raises:
            raise self.raises[object_id]
        return SimpleNamespace(contextual_meaning="cuối cùng thì")


def service(target, *, others=(), existing=(), results=None, raises=None, propagate=False):
    video = Video(id=VIDEO_ID, source="youtube", external_video_id="sample", original_language_code="en",
                  title="sample", processing_status="learning_objects_ready", learning_status="ready")
    videos, transcripts, segments, objects = Mock(), Mock(), Mock(), Mock()
    videos.get_by_id.return_value = video
    transcripts.get_by_id.side_effect = lambda transcript_id: VideoTranscript(
        id=TRANSCRIPT_ID, video_id=VIDEO_ID, language_code="en", is_original=True) if transcript_id == TRANSCRIPT_ID else None
    segments.list_for_transcript.return_value = list(reversed(SEGMENTS))  # order comes from sequence numbers
    by_id = {row.id: row for row in SEGMENTS}
    segments.get_by_id.side_effect = by_id.get
    objects.list_for_video.return_value = list(existing)
    resolution, enrichment = Resolution(results), Enrichment(raises)
    built = RegionPreparationService(
        videos=videos, transcripts=transcripts, segments=segments, learning_objects=objects,
        regions=Regions(target, *others), resolution=resolution, enrichment=enrichment,
        propagate_failures=propagate,
    )
    return built, resolution, enrichment


def test_only_region_segments_are_extracted_with_neighbor_context_from_the_whole_transcript():
    target = region(5, 7)
    built, resolution, _ = service(target)
    outcome = built.prepare_claimed(claim_for(target))
    assert [call[0] for call in resolution.calls] == [SEGMENTS[4].id, SEGMENTS[5].id, SEGMENTS[6].id]
    first, last = resolution.calls[0][1], resolution.calls[-1][1]
    assert first["previous_context"] == SEGMENTS[3].text and last["next_context"] == SEGMENTS[7].text
    assert outcome.status == "no_content"


def test_segments_of_a_finished_region_are_not_extracted_again():
    target = region(5, 7)
    done = region(4, 6, status=RegionPreparationStatus.READY)
    other_version = region(7, 7, status=RegionPreparationStatus.READY, preparation_version="older")
    failed = region(7, 7, status=RegionPreparationStatus.FAILED, support_language_code="vi")
    built, resolution, _ = service(target, others=(done, other_version, failed))
    built.prepare_claimed(claim_for(target))
    assert [call[0] for call in resolution.calls] == [SEGMENTS[6].id]


def test_occurrences_outside_the_region_are_neither_counted_nor_enriched():
    target = region(5, 6)
    inside, outside = occurrence(5), occurrence(9, concept=CONCEPT_B)
    built, _, enrichment = service(target, existing=(inside, outside))
    outcome = built.prepare_claimed(claim_for(target))
    assert [call[0] for call in enrichment.calls] == [inside.id]
    assert enrichment.calls[0][1] == "vi" and outcome.status == "ready" and outcome.usable_count == 1


def test_the_two_occurrence_cap_applies_per_region_not_per_video():
    target = region(8, 10)
    late = [occurrence(8), occurrence(9), occurrence(10)]
    built, _, enrichment = service(target, existing=late)
    outcome = built.prepare_claimed(claim_for(target))
    assert [call[0] for call in enrichment.calls] == [late[0].id, late[1].id]
    assert outcome.usable_count == 2


def test_new_resolved_occurrences_in_the_region_are_prepared():
    target = region(5, 5)
    found = occurrence(5)
    built, _, enrichment = service(target, results={SEGMENTS[4].id: [found]})
    assert built.prepare_claimed(claim_for(target)).status == "ready"
    assert enrichment.calls == [(found.id, "vi")]


def test_sense_mismatch_is_excluded_and_enrichment_failure_propagates_when_claimed():
    target = region(5, 6)
    first, second = occurrence(5), occurrence(6, concept=CONCEPT_B)
    built, _, _ = service(target, existing=(first, second), raises={first.id: DictionarySenseMismatch("no sense")})
    assert built.prepare_claimed(claim_for(target)).usable_count == 1
    failing, _, _ = service(target, existing=(first,), raises={first.id: LearningObjectEnrichmentError("down")},
                            propagate=True)
    with pytest.raises(LearningObjectEnrichmentError):
        failing.prepare_claimed(claim_for(target))
    tolerant, _, _ = service(target, existing=(first,), raises={first.id: LearningObjectEnrichmentError("down")})
    outcome = tolerant.prepare_claimed(claim_for(target))
    assert outcome.status == "failed" and outcome.failure_code == "preparation_incomplete"


def test_one_malformed_model_reply_skips_that_word_instead_of_failing_the_claimed_region():
    """A schema-violating reply for one occurrence is that word's failure; the rest of the region is kept."""
    target = region(5, 6)
    first, second = occurrence(5), occurrence(6, concept=CONCEPT_B)
    bad = LearningObjectEnrichmentError("bad reply")
    bad.__cause__ = LLMProviderError("schema", category=LLMProviderFailureCategory.SCHEMA_VIOLATION)
    built, _, enrichment = service(target, existing=(first, second), raises={first.id: bad}, propagate=True)
    outcome = built.prepare_claimed(claim_for(target))
    assert [call[0] for call in enrichment.calls] == [first.id, second.id]
    assert outcome.status == "ready" and outcome.usable_count == 1 and outcome.partial_failures == 1


def test_a_transport_failure_still_propagates_so_the_claimed_region_is_retried():
    target = region(5, 5)
    first = occurrence(5)
    down = LearningObjectEnrichmentError("down")
    down.__cause__ = LLMProviderError("timeout", category=LLMProviderFailureCategory.TRANSPORT)
    built, _, _ = service(target, existing=(first,), raises={first.id: down}, propagate=True)
    with pytest.raises(LearningObjectEnrichmentError):
        built.prepare_claimed(claim_for(target))


@pytest.mark.parametrize("status", [RegionPreparationStatus.PENDING, RegionPreparationStatus.READY])
def test_an_unclaimed_region_is_not_prepared(status):
    target = region(status=status)
    built, resolution, _ = service(target)
    with pytest.raises(ValueError):
        built.prepare_claimed(claim_for(target))
    assert resolution.calls == []


def test_a_video_stage_claim_cannot_prepare_a_region():
    target = region()
    built, _, _ = service(target)
    with pytest.raises(ValueError):
        built.prepare_claimed(claim_for(target, stage="learning_preparation"))


def test_region_claims_carry_exactly_their_region():
    with pytest.raises(ValueError):
        ContentClaim(intent_id=uuid4(), video_id=VIDEO_ID, stage="region_preparation", generation=1, token=uuid4(),
                     epoch=1, lease_expires_at=datetime.now(UTC))
    with pytest.raises(ValueError):
        ContentClaim(intent_id=uuid4(), video_id=VIDEO_ID, stage="learning_preparation", generation=1,
                     token=uuid4(), epoch=1, lease_expires_at=datetime.now(UTC), region_preparation_id=uuid4())


def test_admission_rows_parse_and_unknown_statuses_fail_closed():
    admitted = RegionAdmission.from_row({"status": "pending", "region_preparation_id": str(uuid4()),
                                         "intent_id": str(uuid4()), "dispatch_now": True})
    assert admitted.dispatch_now and admitted.intent_id is not None
    exhausted = RegionAdmission.from_row({"status": "budget_exhausted", "reset_at": "2026-10-20T01:00:00Z"})
    assert exhausted.reset_at.tzinfo is not None and exhausted.region_preparation_id is None
    with pytest.raises(ValueError):
        RegionAdmission.from_row({"status": "mastered"})


def test_only_finished_regions_count_as_covered():
    rows = [region(1, 2, status=RegionPreparationStatus.READY), region(4, 4, status=RegionPreparationStatus.NO_CONTENT),
            region(6, 9, status=RegionPreparationStatus.PROCESSING)]
    assert covered_sequences(rows) == {1, 2, 4}
    assert covered_sequences(rows, exclude=rows[0].id) == {4}


# --- Workspace: saving a region asks for its preparation -----------------------------------

POLICY = RegionPreparationPolicy(support_language_code="vi", preparation_version=REGION_PREPARATION_VERSION,
                                 limit=20, window_seconds=86400)


def workspace(regions, dispatcher=None):
    owner, item = uuid4(), uuid4()
    video = SimpleNamespace(id=VIDEO_ID, original_language_code="en", duration_ms=60_000,
                            processing_status="learning_objects_ready")
    library, videos, transcripts, segments, store = Mock(), Mock(), Mock(), Mock(), Mock()
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=VIDEO_ID) if (library_item_id, user_id) == (item, owner) else None)
    videos.get_by_id.return_value = video
    transcripts.list_for_video.return_value = [
        SimpleNamespace(id=TRANSCRIPT_ID, is_original=True, language_code="en", source="caption_track")]
    by_id = {row.id: row for row in SEGMENTS}
    segments.get_by_id.side_effect = by_id.get
    store.save_region.side_effect = lambda **kwargs: LearnerVideoWorkspace(
        library_item_id=kwargs["library_item_id"], user_id=kwargs["user_id"],
        region_transcript_id=kwargs["transcript_id"], region_start_segment_id=kwargs["start_segment_id"],
        region_end_segment_id=kwargs["end_segment_id"])
    built = VideoWorkspaceService(library=library, videos=videos, transcripts=transcripts, segments=segments,
                                  workspaces=store, regions=regions, dispatcher=dispatcher,
                                  preparation_policy=POLICY)
    return built, SimpleNamespace(id=owner), item, store


def request(start=3, end=5):
    return StudyRegionRequest(start_segment_id=SEGMENTS[start - 1].id, end_segment_id=SEGMENTS[end - 1].id)


def test_saving_a_region_admits_its_preparation_and_dispatches_new_work():
    regions, dispatcher = Mock(), Mock()
    intent = uuid4()
    regions.admit.return_value = RegionAdmission(status="pending", region_preparation_id=uuid4(),
                                                 intent_id=intent, dispatch_now=True)
    built, user, item, _ = workspace(regions, dispatcher)
    view = built.save_region(user, item, request())
    kwargs = regions.admit.call_args.kwargs
    assert kwargs["user_id"] == user.id and kwargs["library_item_id"] == item
    assert kwargs["transcript_id"] == TRANSCRIPT_ID and kwargs["start_segment_id"] == SEGMENTS[2].id
    assert kwargs["support_language_code"] == "vi" and kwargs["preparation_version"] == REGION_PREPARATION_VERSION
    assert kwargs["limit"] == 20 and kwargs["window_seconds"] == 86400 and kwargs["max_segments"] == 40
    dispatcher.dispatch.assert_called_once_with(intent)
    assert view.region.preparation.status == "pending"
    regions.find.assert_not_called()


def test_a_region_already_prepared_or_in_progress_is_not_dispatched_again():
    regions, dispatcher = Mock(), Mock()
    regions.admit.return_value = RegionAdmission(status="ready", region_preparation_id=uuid4(), usable_count=4)
    built, user, item, _ = workspace(regions, dispatcher)
    view = built.save_region(user, item, request())
    dispatcher.dispatch.assert_not_called()
    assert view.region.preparation.status == "ready" and view.region.preparation.usable_count == 4


def test_budget_exhaustion_keeps_the_region_and_reports_when_it_resets():
    regions = Mock()
    reset = datetime(2026, 10, 20, 1, tzinfo=UTC)
    regions.admit.return_value = RegionAdmission(status="budget_exhausted", reset_at=reset)
    built, user, item, store = workspace(regions, Mock())
    view = built.save_region(user, item, request())
    store.save_region.assert_called_once()
    assert view.region is not None and view.region.preparation.status == "budget_exhausted"
    assert view.region.preparation.reset_at == reset


def test_admission_and_dispatch_failures_never_fail_the_region_save():
    regions, dispatcher = Mock(), Mock()
    regions.admit.side_effect = RuntimeError("database unavailable")
    built, user, item, _ = workspace(regions, dispatcher)
    assert built.save_region(user, item, request()).region.preparation.status == "unavailable"
    regions.admit.side_effect = None
    regions.admit.return_value = RegionAdmission(status="pending", intent_id=uuid4(), dispatch_now=True)
    dispatcher.dispatch.side_effect = RuntimeError("broker down")
    assert built.save_region(user, item, request()).region.preparation.status == "pending"


def test_reading_the_workspace_reports_readiness_without_admitting():
    regions = Mock()
    regions.find.return_value = region(3, 5, status=RegionPreparationStatus.FAILED, retryable=True)
    built, user, item, store = workspace(regions, Mock())
    store.get_for_user.return_value = LearnerVideoWorkspace(
        library_item_id=item, user_id=user.id, region_transcript_id=TRANSCRIPT_ID,
        region_start_segment_id=SEGMENTS[2].id, region_end_segment_id=SEGMENTS[4].id)
    view = built.get(user, item)
    regions.admit.assert_not_called()
    assert view.region.preparation.status == "failed" and view.region.preparation.retryable
    regions.find.return_value = None
    assert built.get(user, item).region.preparation is None


def test_store_and_policy_are_configured_together():
    with pytest.raises(ValueError):
        VideoWorkspaceService(library=Mock(), videos=Mock(), transcripts=Mock(), segments=Mock(),
                              workspaces=Mock(), regions=Mock())


# --- Worker and dispatch -------------------------------------------------------------------

def test_region_intents_publish_to_the_region_task(monkeypatch):
    published = []
    monkeypatch.setattr(worker.prepare_video_region, "apply_async",
                        lambda **kwargs: published.append(kwargs) or SimpleNamespace(id="task"))
    monkeypatch.setattr(worker.prepare_video_learning_content, "apply_async",
                        lambda **kwargs: pytest.fail("Video preparation task used for a region"))

    class Connection:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.platform.celery.celery_app.connection_for_write", lambda **kwargs: Connection())
    intent = SimpleNamespace(id=uuid4(), stage="region_preparation")
    assert dispatch_module._publish(intent) == "task"
    assert published[0]["args"] == [str(intent.id)]


def test_worker_claims_with_the_region_version_and_records_the_outcome_on_the_region(monkeypatch):
    target = region()
    claim = claim_for(target)
    intents = Mock()
    intents.get.return_value = SimpleNamespace(stage="region_preparation")
    intents.claim.return_value = claim
    prepared = Mock()
    prepared.prepare_claimed.return_value = SimpleNamespace(status="ready", usable_count=3, failure_code=None)
    monkeypatch.setattr(worker, "supabase_service", object())
    monkeypatch.setattr(worker, "build_work_intents", lambda _: intents)
    monkeypatch.setattr(worker, "build_region_preparation_service", lambda _, claim: prepared)
    result = worker.prepare_video_region.run(str(claim.intent_id))
    assert intents.claim.call_args.kwargs["preparation_version"] == REGION_PREPARATION_VERSION
    intents.finish_region_preparation.assert_called_once_with(claim, status="ready", usable_count=3,
                                                              failure_code=None)
    intents.finish_preparation.assert_not_called()
    assert result["status"] == "ready" and result["region_preparation_id"] == str(target.id)


def test_worker_never_claims_a_video_stage_intent_as_a_region(monkeypatch):
    intents = Mock()
    intents.get.return_value = SimpleNamespace(stage="learning_preparation")
    monkeypatch.setattr(worker, "supabase_service", object())
    monkeypatch.setattr(worker, "build_work_intents", lambda _: intents)
    assert worker.prepare_video_region.run(str(uuid4()))["status"] == "not_claimed"
    intents.claim.assert_not_called()


def test_a_failed_region_outcome_is_recorded_as_a_bounded_failure(monkeypatch):
    target = region()
    claim = claim_for(target)
    intents = Mock()
    intents.get.return_value = SimpleNamespace(stage="region_preparation")
    intents.claim.return_value = claim
    intents.record_failure.return_value = "failed"
    prepared = Mock()
    prepared.prepare_claimed.return_value = SimpleNamespace(status="failed", usable_count=0,
                                                            failure_code="preparation_incomplete")
    monkeypatch.setattr(worker, "supabase_service", object())
    monkeypatch.setattr(worker, "build_work_intents", lambda _: intents)
    monkeypatch.setattr(worker, "build_region_preparation_service", lambda _, claim: prepared)
    assert worker.prepare_video_region.run(str(claim.intent_id))["status"] == "failed"
    intents.finish_region_preparation.assert_not_called()
    assert intents.record_failure.call_args.kwargs["failure_class"] == "permanent"


# --- Migration contract (real behaviour is verified on the development database) ----------

def _function(sql: str, name: str) -> str:
    start = sql.index(f"create or replace function v3.{name}(")
    return sql[start:sql.index("end $$;", start)]


def test_region_branches_change_only_the_region_row():
    sql = MIGRATION.read_text(encoding="utf-8")
    for name in ("claim_leased_content_work", "record_content_work_failure", "recover_expired_content_work"):
        body = _function(sql, name)
        assert "elsif i.stage = 'learning_preparation' then" in body
        assert "update v3.video_region_preparations" in body
    claim = _function(sql, "claim_leased_content_work")
    assert "p_preparation_version is distinct from r.preparation_version" in claim
    assert "'preparation_version_changed'" in claim


def test_fenced_shared_content_writes_accept_both_preparation_stages_and_fence_the_range():
    sql = MIGRATION.read_text(encoding="utf-8")
    for name in ("resolve_claimed_concept", "resolve_claimed_occurrence", "enrich_claimed_occurrence",
                 "link_claimed_concept_reference"):
        body = _function(sql, name)
        assert "v3.lock_current_preparation_claim(p_intent_id, p_claim_token, p_claim_epoch)" in body
        assert "'learning_preparation')" not in body
    for name in ("resolve_claimed_occurrence", "enrich_claimed_occurrence"):
        assert "preparation_claim_covers_segment" in _function(sql, name)


def test_video_stage_uniqueness_is_kept_and_region_stage_gets_its_own():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "on v3.video_work_intents (video_id, stage, generation) where stage <> 'region_preparation'" in sql
    assert "on v3.video_work_intents (region_preparation_id, generation) where stage = 'region_preparation'" in sql
    assert "and stage <> 'region_preparation';" in sql and "and stage = 'region_preparation';" in sql
    assert "check ((stage = 'region_preparation') = (region_preparation_id is not null))" in sql


def test_new_tables_and_functions_are_service_role_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in ("video_region_preparations", "learner_region_preparation_requests"):
        assert f"alter table v3.{table} enable row level security;" in sql
        assert f"revoke all privileges on v3.{table} from public, anon, authenticated;" in sql
    for name in ("lock_current_preparation_claim", "preparation_claim_covers_segment",
                 "complete_claimed_region_preparation", "admit_region_preparation"):
        assert f"revoke all on function v3.{name}(" in sql and f"grant execute on function v3.{name}(" in sql
    assert "grant select" not in sql
