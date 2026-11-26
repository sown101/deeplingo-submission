"""A trusted curriculum grammar occurrence reaches playback without a vocabulary meaning."""
from types import SimpleNamespace
from uuid import uuid4

from app.modules.content.domain.knowledge import ConceptType
from tests.content.test_video_playback import fixture  # noqa: F401


def test_grammar_annotation_survives_without_prepared_meaning(fixture):
    f = fixture
    f.video.original_language_code = "en"
    f.tracks.list_for_video.return_value = [SimpleNamespace(
        id=uuid4(), is_original=True, language_code="en", source="caption_track")]
    f.rows[0]["text"] = "I am happy."
    occurrence_id, concept_id = uuid4(), uuid4()
    f.rows[0]["learning_objects"] = [{
        "id": str(occurrence_id), "concept_id": str(concept_id),
        "start_codepoint": 2, "end_codepoint": 4, "evidence_text": "am",
        "concepts": {"type": ConceptType.GRAMMAR.value, "language_code": "en", "sense_key": "en.be_present",
                     "metadata": {"grammar_key": "en.be_present"}},
        "raw_ai_diagnostics": {},
    }]
    response = f.client.get(f"{f.url}/transcript", headers={"Authorization": "Bearer owner.test.jwt"})
    assert response.status_code == 200
    assert response.json()["segments"][0]["learning_objects"] == [{
        "learning_object_id": str(occurrence_id), "start_codepoint": 2, "end_codepoint": 4,
        "grammar_key": "en.be_present",
    }]
    assert "raw_ai_diagnostics" not in response.text
