"""Learner data export: only the signed-in learner's rows, no hidden answers or internals."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_learner_data_export_service
from app.main import app
from app.modules.content.infrastructure.data_export import ConceptLabels, LibraryDataSection
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.data_export import EXPORT_FORMAT, LearnerDataExportService
from app.modules.learner.infrastructure.data_export import LearnerOwnDataSection
from app.modules.learning.infrastructure.data_export import LearningDataSection
from app.modules.review.infrastructure.data_export import ReviewDataSection
from app.platform.persistence import SelectTooLarge

USER, OTHER = str(uuid4()), str(uuid4())
CONCEPT = str(uuid4())


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table, self.columns, self.eqs, self.ins = db, table, "*", {}, None
        self.window = slice(None)

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.eqs[column] = value
        return self

    def in_(self, column, values):
        self.ins = (column, set(values))
        return self

    def limit(self, _):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self.window = slice(start, end + 1)
        return self

    def execute(self):
        self.db.queries.append((self.table, self.columns, dict(self.eqs)))
        rows = [row for row in self.db.tables.get(self.table, [])
                if all(row.get(column) == value for column, value in self.eqs.items())
                and (self.ins is None or row.get(self.ins[0]) in self.ins[1])]
        wanted = self.columns.split(",")
        return SimpleNamespace(data=[{key: row.get(key) for key in wanted} for row in rows[self.window]])


class FakeClient:
    def __init__(self, tables):
        self.tables, self.queries = tables, []

    def schema(self, name):
        assert name == "v3"
        return self

    def table(self, name):
        return FakeQuery(self, name)


def database():
    state = str(uuid4())
    video, item = str(uuid4()), str(uuid4())
    return FakeClient({
        "profiles": [{"id": USER, "display_name": "Sơn", "timezone": "Asia/Ho_Chi_Minh", "created_at": "t"},
                     {"id": OTHER, "display_name": "Someone else"}],
        "learner_agent_consent": [{"user_id": USER, "voice_consent": True, "decided_at": "t", "updated_at": "t"},
                                  {"user_id": OTHER, "voice_consent": False, "decided_at": "t", "updated_at": "t"}],
        "learner_personalization_signals": [
            {"user_id": USER, "language_code": "en", "kind": "error_type", "code": "verb_tense", "usage_count": 3,
             "created_at": "t", "updated_at": "t"},
            {"user_id": OTHER, "language_code": "en", "kind": "topic", "code": "food", "usage_count": 1,
             "created_at": "t", "updated_at": "t"}],
        "learner_videos": [{"id": item, "user_id": USER, "video_id": video, "created_at": "t"}],
        "learner_video_workspaces": [{"library_item_id": item, "user_id": USER, "position_ms": 520_000},
                                     {"library_item_id": str(uuid4()), "user_id": OTHER, "position_ms": 1}],
        "videos": [{"id": video, "title": "Neil's job", "external_video_id": "abc"}],
        "review_states": [{"id": state, "user_id": USER, "concept_id": CONCEPT, "review_mode": "recall",
                           "due_at": "t", "stability": 3.2, "difficulty": 5.1}],
        "review_events": [{"review_state_id": state, "rating": 3, "reviewed_at": "t",
                           "previous_scheduling_state": {"stability": 1}}],
        "concepts": [{"id": CONCEPT, "canonical_text": "fly"}],
    })


def exporter(db):
    return LearnerDataExportService(
        sections=[LearnerOwnDataSection(db), LibraryDataSection(db), LearningDataSection(db),
                  ReviewDataSection(db)],
        concept_labels=ConceptLabels(db),
    )


def test_export_contains_only_the_learners_rows_and_labels_referenced_concepts():
    db = database()
    document = exporter(db).export(USER)

    assert document["format"] == EXPORT_FORMAT and document["user_id"] == USER
    assert document["learner"]["profile"]["display_name"] == "Sơn"
    assert "known_concepts" not in document["learner"]
    # FR-6.2: the export carries the voice consent record and the personalization signals, only the learner's own.
    assert document["learner"]["voice_consent"]["voice_consent"] is True
    assert [(row["kind"], row["code"], row["usage_count"]) for row in document["learner"]["personalization_signals"]]         == [("error_type", "verb_tense", 3)]
    assert "companion_memory" not in document["learner"]
    # FR-4.2: the facts behind the practice streak are in the learning log section (one log since 2026-11-18).
    assert "speaking_activity" not in document["learning"] and "practice_events" not in document["learning"]
    assert document["library"][0]["video"]["title"] == "Neil's job"
    assert [row["watch_position_ms"] for row in document["library"]] == [520_000]
    assert "assessment" not in document and "sessions" not in document["learning"]
    assert document["review"]["review_events"][0]["rating"] == 3
    assert document["concepts"] == {CONCEPT: "fly"}
    for table, _, filters in db.queries:
        if table in {"review_states", "learner_videos",
                     "learner_agent_consent", "learner_personalization_signals", "learner_video_workspaces"}:
            assert filters == {"user_id": USER}


def test_export_leaves_out_hidden_answers_ai_diagnostics_and_scheduling_internals():
    text = str(exporter(database()).export(USER))
    for hidden in ("secret", "expected_response_payload", "prompt_payload", "raw_ai_diagnostics", "internal",
                   "stability", "difficulty", "previous_scheduling_state", "Someone else"):
        assert hidden not in text


def test_section_names_must_be_unique():
    db = database()
    with pytest.raises(ValueError):
        LearnerDataExportService(sections=[LibraryDataSection(db), LibraryDataSection(db)])


def test_export_includes_word_favorites():
    db = database()
    db.tables["saved_concepts"] = [{"user_id": USER, "concept_id": CONCEPT, "favorite": True}]
    assert exporter(db).export(USER)["learner"]["saved_concepts"][0]["favorite"] is True


@pytest.mark.parametrize("table", ["learner_speech_transcripts", "learner_pronunciation_scores", "learner_agent_memory"])
def test_export_cannot_return_a_partial_file_when_a_section_is_too_large(table, monkeypatch):
    db = database()
    original = db.table

    def fetch(name):
        if name == table:
            raise SelectTooLarge(name)
        return original(name)

    monkeypatch.setattr(db, "table", fetch)
    with pytest.raises(SelectTooLarge):
        exporter(db).export(USER)


def test_export_route_is_authenticated_and_downloads_a_json_file():
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=USER)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_learner_data_export_service] = lambda: exporter(database())
    try:
        client = TestClient(app)
        assert client.get("/api/v1/v3/learner/me/export").status_code == 401
        response = client.get("/api/v1/v3/learner/me/export", headers={"Authorization": "Bearer owner.test.jwt"})
        assert response.status_code == 200
        assert response.headers["content-disposition"] == 'attachment; filename="deeplingo-my-data.json"'
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["user_id"] == USER
        assert client.get(f"/api/v1/v3/learner/me/export?user_id={OTHER}",
                          headers={"Authorization": "Bearer owner.test.jwt"}).json()["user_id"] == USER
    finally:
        app.dependency_overrides.clear()
