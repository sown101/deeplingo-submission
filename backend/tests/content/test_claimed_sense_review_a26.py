"""A26: the claimed no-matching-sense review (migration checked statically; applying it needs approval)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20261021100000_claimed_sense_review_a26.sql"


@pytest.fixture(scope="module")
def body():
    sql = MIGRATION.read_text(encoding="utf-8")
    start = sql.index("create or replace function v3.record_claimed_sense_review(")
    return sql[start:sql.index("$$;", start)]


@pytest.fixture(scope="module")
def sql():
    return MIGRATION.read_text(encoding="utf-8")


def test_it_runs_as_the_caller_with_an_empty_search_path_for_the_service_role_only(body, sql):
    assert "security invoker" in body and "set search_path = ''" in body
    signature = "v3.record_claimed_sense_review(uuid, uuid, bigint, uuid, text, jsonb)"
    assert f"revoke all on function {signature} from public, anon, authenticated;" in sql
    assert f"grant execute on function {signature} to service_role;" in sql
    assert "security definer" not in sql


def test_it_locks_the_claim_first_and_stays_inside_the_claimed_video_and_region(body):
    lock = body.index("v3.lock_current_preparation_claim(p_intent_id, p_claim_token, p_claim_epoch)")
    occurrence = body.index("video_id = i.video_id for update")
    region = body.index("v3.preparation_claim_covers_segment(i.stage, i.region_preparation_id, lo.transcript_segment_id)")
    assert lock < occurrence < region < body.index("update v3.learning_objects set")


def test_it_accepts_only_a_well_formed_review_of_this_occurrence(body):
    for check in ("p_review->>'status' is distinct from 'no_matching_sense'",
                  "p_review->>'concept_id' is distinct from lo.concept_id::text",
                  "coalesce(btrim(p_review->>'prompt_version'), '') = ''",
                  "jsonb_typeof(p_review->'offered_sense_ids') is distinct from 'array'",
                  "sense_key = p_review->>'concept_sense_key'",
                  "lang = ''"):
        assert check in body, check
    assert body.count("errcode = '23514'") >= 3


def test_it_withdraws_this_languages_meaning_and_records_the_review_from_the_locked_row(body):
    assert "diag := coalesce(lo.raw_ai_diagnostics, '{}'::jsonb);" in body
    assert "'enrichments', langs - lang" in body
    assert "jsonb_build_object(lang, p_review)" in body and "'dictionary_review'" in body
    assert re.search(r"if diag->'enrichment'->>'target_language_code' = lang then\s+diag := diag - 'enrichment';", body)


def test_a_meaning_of_the_same_version_stored_first_by_another_claim_is_kept(body):
    keep = body.index("langs->lang->>'prompt_version' = p_review->>'prompt_version'")
    assert keep < body.index("update v3.learning_objects set")
    assert "return to_jsonb(lo);  -- another claim stored a meaning of this version first" in body


def test_it_writes_nothing_but_the_occurrence_diagnostics(body):
    assert body.count("update ") == 1 and "insert into" not in body and "delete from" not in body
    update = body[body.index("update v3.learning_objects set"):]
    assert "raw_ai_diagnostics = diag" in update and "difficulty_score" not in update
