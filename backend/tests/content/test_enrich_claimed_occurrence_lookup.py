"""enrich_claimed_occurrence finds the dictionary entry by primary key (statement timeout on dev, 2026-11-15)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase/migrations"
MIGRATION = MIGRATIONS / "20261115090000_enrich_claimed_occurrence_entry_lookup.sql"
PREVIOUS = MIGRATIONS / "20261020090000_quick_review_completion_m1s7d.sql"


def _function(sql: str) -> str:
    start = sql.index("create or replace function v3.enrich_claimed_occurrence(")
    return sql[start:sql.index("end $$;", start)]


def test_the_latest_definition_is_this_migration():
    later = [p.name for p in MIGRATIONS.glob("*.sql")
             if p.name > MIGRATION.name and "function v3.enrich_claimed_occurrence(" in p.read_text(encoding="utf-8")]
    assert MIGRATION.exists() and later == []


def test_the_entry_is_looked_up_by_uuid_not_by_text():
    body = _function(MIGRATION.read_text(encoding="utf-8"))
    assert "id::text =" not in body
    assert "select * into entry from v3.dictionary_entries where id = entry_id;" in body
    # A non-canonical id matched nothing before; it still matches nothing instead of failing the cast.
    assert "~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'" in body


def test_only_the_lookup_changed():
    old = _function(PREVIOUS.read_text(encoding="utf-8"))
    new = _function(MIGRATION.read_text(encoding="utf-8"))
    before, after = old.split("    select * into entry from v3.dictionary_entries\n")
    assert new.startswith(before.replace("entry v3.dictionary_entries%rowtype;",
                                         "entry v3.dictionary_entries%rowtype; entry_id uuid;"))
    assert new.endswith(after.split("\n", 1)[1])


def test_grants_stay_service_role_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    signature = "v3.enrich_claimed_occurrence(uuid, uuid, bigint, uuid, jsonb)"
    assert f"revoke all on function {signature} from public, anon, authenticated;" in sql
    assert f"grant execute on function {signature} to service_role;" in sql
    assert "security invoker set search_path = ''" in sql
