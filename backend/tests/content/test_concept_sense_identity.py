from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.content.domain.knowledge import Concept, ConceptType
from app.modules.review.domain.models import FSRSState, ReviewMode, ReviewState
from app.modules.content.application.knowledge_resolution import normalize_sense_key
from app.modules.content.infrastructure.repositories.concepts import ConceptRepository


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "20260924023458_v5l4_concept_sense_identity.sql"
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
FINANCIAL_ID = UUID("22222222-2222-2222-2222-222222222222")
RIVER_ID = UUID("33333333-3333-3333-3333-333333333333")
ACTIVITY_ID = UUID("44444444-4444-4444-4444-444444444444")
ATTEMPT_ID = UUID("55555555-5555-5555-5555-555555555555")
NOW = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)


def _concept(concept_id: UUID, sense_key: str) -> Concept:
    return Concept(
        id=concept_id,
        language_code="en",
        type=ConceptType.VOCABULARY,
        canonical_text="bank",
        normalized_text="bank",
        sense_key=sense_key,
    )


class _Query:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.filters = []
        self.conflict = None
        self.payload = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _count):
        return self

    def upsert(self, payload, *, on_conflict):
        self.payload = payload
        self.conflict = on_conflict
        return self

    def execute(self):
        return type("Result", (), {"data": self.rows})()


class _Client:
    def __init__(self, rows):
        self.query = _Query(rows)

    def schema(self, schema):
        assert schema == "v3"
        return self

    def table(self, table):
        assert table == "concepts"
        return self.query


class _ReviewStates:
    def __init__(self, rows):
        self.rows = rows

    def list_available_for_user(self, *, user_id, due_at, limit=50):
        return [row for row in self.rows if row.user_id == user_id and row.due_at <= due_at][:limit]


class _Concepts:
    def __init__(self, rows):
        self.rows = {row.id: row for row in rows}

    def get_by_id(self, concept_id):
        return self.rows.get(concept_id)


def _review_state(state_id: UUID, concept_id: UUID) -> ReviewState:
    return ReviewState(
        id=state_id,
        user_id=USER_ID,
        concept_id=concept_id,
        review_mode=ReviewMode.CONCEPT_TO_MEANING,
        stability=2,
        difficulty=5,
        elapsed_days=1,
        scheduled_days=1,
        reps=1,
        lapses=0,
        fsrs_state=FSRSState.REVIEW,
        due_at=NOW - timedelta(minutes=1),
        last_reviewed_at=NOW - timedelta(days=1),
    )


def test_forward_migration_replaces_lexical_uniqueness_without_broadening_security():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "add column if not exists sense_key text" in sql
    assert "legacy:' || id::text" in sql
    assert "concept_sense_identity_collision_count" in sql
    assert "drop constraint if exists concepts_unique_normalized" in sql
    assert "unique (language_code, type, normalized_text, sense_key)" in sql
    assert "alter column sense_key set not null" in sql
    assert "enable row level security" not in sql
    assert "create policy" not in sql
    assert " grant " not in f" {sql} "


def test_repository_lookup_and_upsert_use_the_complete_semantic_identity():
    row = _concept(FINANCIAL_ID, "financial institution").model_dump(mode="json")
    lookup_client = _Client([row])
    repository = ConceptRepository(lookup_client)

    found = repository.find_by_identity(
        language_code="en",
        concept_type="vocabulary",
        normalized_text="bank",
        sense_key="financial institution",
    )

    assert found.id == FINANCIAL_ID
    assert lookup_client.query.filters == [
        ("language_code", "en"),
        ("type", "vocabulary"),
        ("normalized_text", "bank"),
        ("sense_key", "financial institution"),
    ]

    upsert_client = _Client([row])
    persisted = ConceptRepository(upsert_client).upsert_by_identity(row)
    assert persisted.id == FINANCIAL_ID
    assert upsert_client.query.conflict == "language_code,type,normalized_text,sense_key"


def test_sense_normalization_is_deterministic_conservative_and_support_language_independent():
    assert normalize_sense_key("  “Financial   Institution”  ") == "financial institution"
    assert normalize_sense_key("river-edge") == "river-edge"
    assert normalize_sense_key("river edge") == "river edge"
