from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "20260920155040_v5l1_supabase_security_hardening.sql"
ANSWER_READS = ROOT / "supabase" / "migrations" / "20261017150000_revoke_direct_answer_reads_sec01.sql"
PROFILE_LIFECYCLE = ROOT / "supabase" / "migrations" / "20261017170000_profile_lifecycle_server_only_sec03.sql"
SMOKE = ROOT / "scripts" / "platform" / "smoke_supabase_security.py"


def _migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").casefold()


def test_authority_tables_revoke_authenticated_mutation() -> None:
    sql = _migration_sql()
    for table in (
        "v3.learner_skill_states",
        "v3.concept_mastery",
        "v3.learning_sessions",
        "v3.session_activities",
        "v3.attempts",
        "v3.assessments",
        "v3.review_states",
        "v3.review_events",
        "v3.assessment_applications",
        "v3.review_materializations",
    ):
        assert table in sql
    assert "revoke insert, update, delete on" in sql
    assert "from authenticated" in sql


def test_legacy_tables_enable_rls_and_views_use_invoker_security() -> None:
    sql = _migration_sql()
    for table in (
        "language_config",
        "channels",
        "videos",
        "subtitles",
        "vocabulary_master",
        "user_library",
        "user_language_preferences",
        "user_vocabulary_progress",
        "learning_activities",
        "saved_words",
        "word_group_members",
        "word_groups",
        "flashcards",
        "flashcard_reviews",
    ):
        assert f"alter table public.{table} enable row level security" in sql
    for view in ("v_videos_with_language", "v_user_library_details", "v_smart_groups"):
        assert f"alter view public.{view} set (security_invoker = true)" in sql


def test_critical_rpcs_are_service_only() -> None:
    sql = _migration_sql()
    for function in (
        "apply_assessment_application(jsonb)",
        "reserve_review_materialization(jsonb)",
        "start_or_resume_review_session(uuid, text, jsonb, integer)",
    ):
        assert f"revoke execute on function v3.{function}" in sql
        assert f"grant execute on function v3.{function}" in sql


def test_security_smoke_has_production_and_project_guards() -> None:
    source = SMOKE.read_text(encoding="utf-8")
    assert 'environment == "production"' in source
    assert "ALLOW_TEST_SEEDING" in source
    assert "SMOKE_EXPECTED_SUPABASE_PROJECT_REF" in source
    assert "secrets.compare_digest" in source


def test_learners_cannot_read_grading_truth_through_the_data_api() -> None:
    """SEC-01: expected answers and AI diagnostics are server-only columns."""
    sql = ANSWER_READS.read_text(encoding="utf-8").casefold()
    statement = sql[sql.index("revoke select on"):]
    assert "v3.session_activities" in statement
    assert "v3.assessments" in statement
    assert "from anon, authenticated;" in statement



def test_learners_cannot_delete_and_recreate_their_profile() -> None:
    """SEC-03: profile deletion cascades to the import budget ledger and learner state."""
    sql = PROFILE_LIFECYCLE.read_text(encoding="utf-8").casefold()
    assert "revoke insert, delete on v3.profiles from anon, authenticated;" in sql
    assert 'drop policy if exists "users can insert own profile" on v3.profiles;' in sql
    assert 'drop policy if exists "users can delete own profile" on v3.profiles;' in sql
    assert "update" not in sql.split("revoke", 1)[1].split(";", 1)[0]
