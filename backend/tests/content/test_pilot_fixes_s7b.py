"""M1 S7b: content fixes before the pilot (admission cap, meaning writes, partial parts, SQL)."""
from pathlib import Path
from unittest.mock import Mock

from app.modules.content.application.enrichment import LearningObjectEnrichmentError
from app.modules.content.application.prompts import LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION
from app.modules.content.domain.region_preparation import (
    PARTIAL_PREPARATION,
    RegionAdmission,
    RegionPreparationStatus,
    covered_sequences,
)
from tests.content.test_learning_object_enrichment import FakeLearningObjects, LO_ID, make_service
from tests.content.test_region_preparation import (
    Enrichment,
    claim_for,
    occurrence,
    region,
    request,
    service,
    workspace,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20261019220000_pilot_fixes_m1s7b.sql"


def _function(sql: str, name: str) -> str:
    start = sql.index(f"create or replace function v3.{name}(")
    end = sql.find("$$;", start)
    return sql[start:end if end != -1 else None]


# --- 1. Region admission joins the shared Content admission ---------------------------------

def test_a_busy_admission_keeps_the_part_and_is_not_dispatched():
    regions, dispatcher = Mock(), Mock()
    regions.admit.return_value = RegionAdmission.from_row({"status": "busy", "retryable": True})
    built, user, item, store = workspace(regions, dispatcher)
    view = built.save_region(user, item, request())
    store.save_region.assert_called_once()
    dispatcher.dispatch.assert_not_called()
    assert view.region.preparation.status == "busy" and view.region.preparation.retryable


def test_region_admission_takes_the_admission_lock_first_and_respects_the_shared_cap():
    body = _function(MIGRATION.read_text(encoding="utf-8"), "admit_region_preparation")
    lock = body.index("perform pg_advisory_xact_lock(6202050::bigint);")
    assert lock < body.index("from v3.videos where id = lv.video_id for update")
    cap = body.index("where state in ('pending', 'dispatched', 'running')) >= 50")
    # Checked before a retry is re-admitted and before a new region is charged or created.
    assert cap < body.index("update v3.video_region_preparations set status = 'pending'")
    assert cap < body.index("insert into v3.learner_region_preparation_requests")
    assert "'status', 'busy'" in body


# --- 2. Meanings: first per language and prompt version, never an older version ------------

def test_a_meaning_from_another_prompt_version_is_made_again():
    service, objects, provider = make_service()
    first = service.enrich(LO_ID, target_language_code="vi")
    assert first is not None and provider.calls == 1
    stored = dict(objects.row.raw_ai_diagnostics)
    old = {**stored["enrichments"]["vi"], "prompt_version": "learning_object_enrichment_v1"}
    objects.row = objects.row.model_copy(update={"raw_ai_diagnostics": {"enrichments": {"vi": old}, "enrichment": old}})
    service.enrich(LO_ID, target_language_code="vi")
    assert provider.calls == 2
    assert objects.row.raw_ai_diagnostics["enrichments"]["vi"]["prompt_version"] == LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION
    service.enrich(LO_ID, target_language_code="vi")
    assert provider.calls == 2  # the current version is reused


def test_when_another_claim_stored_the_meaning_first_the_stored_one_is_reported():
    class FirstWins(FakeLearningObjects):
        """Like the claimed write: an existing meaning of this version is kept."""

        def update_enrichment(self, learning_object_id, data):
            self.update_count += 1
            new = data["raw_ai_diagnostics"]["enrichment"]
            winner = {**new, "contextual_meaning": "đã có trước", "generated_at": "2026-10-19T00:00:00+00:00"}
            self.row = self.row.model_copy(update={"raw_ai_diagnostics": {"enrichments": {"vi": winner},
                                                                          "enrichment": winner}})
            return self.row

    service, objects, _ = make_service()
    service.learning_objects = FirstWins(objects.row)
    result = service.enrich(LO_ID, target_language_code="vi")
    assert result.contextual_meaning == "đã có trước"


def test_the_claimed_write_keeps_the_first_meaning_of_a_version():
    body = _function(MIGRATION.read_text(encoding="utf-8"), "enrich_claimed_occurrence")
    keep = body.index("langs->lang->>'prompt_version' = p_enrichment->>'prompt_version'")
    assert keep < body.index("update v3.learning_objects set")
    assert "return to_jsonb(lo);  -- another claim stored this meaning first" in body
    assert "coalesce(btrim(p_enrichment->>'prompt_version'), '') = ''" in body


# --- 3. A partly prepared part is usable but not covered ------------------------------------

def test_a_part_with_failed_sentences_is_ready_but_not_covered():
    target = region(5, 6)
    good, bad = occurrence(5), occurrence(6)
    built, _, _ = service(target, existing=[good, bad], raises={bad.id: LearningObjectEnrichmentError("x")})
    outcome = built.prepare_claimed(claim_for(target))
    assert outcome.status == "ready" and outcome.failure_code == PARTIAL_PREPARATION
    partial = region(5, 6, status=RegionPreparationStatus.READY, failure_code=PARTIAL_PREPARATION)
    complete = region(7, 8, status=RegionPreparationStatus.READY)
    assert covered_sequences([partial, complete]) == {7, 8}


def test_a_fully_prepared_part_still_has_no_failure_code():
    target = region(5, 5)
    built, _, enrichment = service(target, existing=[occurrence(5)])
    assert isinstance(enrichment, Enrichment)
    outcome = built.prepare_claimed(claim_for(target))
    assert outcome.status == "ready" and outcome.failure_code is None


# --- 4. Quick review RPC and retention SQL ---------------------------------------------------

def test_the_quick_review_rpc_takes_exactly_one_source_and_fails_closed_on_missing_fields():
    body = _function(MIGRATION.read_text(encoding="utf-8"), "start_or_resume_quick_review_session").replace("$fn$", "")
    assert "(v_example is null) = (v_object is null)" in body
    assert "(v_prov->>'source_learning_object_id') is distinct from v_object::text" in body
    assert "(v_prov->>'source_example_sentence_id') is distinct from v_example::text" in body
    assert body.count("true) then") >= 2  # both payload checks are coalesce(..., true)
    assert "join v3.learner_videos lv on lv.video_id = lo.video_id and lv.user_id = p_user_id" in body


def test_expired_rows_are_unreadable_and_purged_by_a_service_role_function():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sql.count("using ((select auth.uid()) = user_id and expires_at > now());") == 2
    purge = _function(sql, "purge_expired_learner_data")
    assert "where expires_at <= now() limit p_limit" in purge
    assert "revoke all on function v3.purge_expired_learner_data(integer) from public, anon, authenticated;" in sql
    assert "grant execute on function v3.purge_expired_learner_data(integer) to service_role;" in sql
    assert "grant select" not in sql  # no new read grants
