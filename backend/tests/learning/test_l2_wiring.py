from unittest.mock import Mock

from app.bootstrap.wiring import speaking
from app.modules.learning.application.selected_targets import SelectedTargetCatalog


def test_real_companion_factory_receives_selected_targets(monkeypatch):
    monkeypatch.setattr(speaking, "_require_database", lambda: Mock())
    # No database in tests: the learner and agent services this factory composes get a stand-in client too.
    from app.bootstrap.wiring import agent
    monkeypatch.setattr("app.bootstrap.wiring.clients.supabase_service", Mock())
    monkeypatch.setattr("app.bootstrap.wiring.content.supabase_service", Mock())
    for cached in (agent.get_learner_facts, agent.get_agent_memory, agent.get_context_builder):
        cached.cache_clear()
    for name in ("_language_model", "_pronunciation_assessor",
                 "_speech_synthesizer", "_companion_ticket_codec",
                 "get_word_concept_service",
                 "_study_regions", "_practice_log"):
        monkeypatch.setattr(speaking, name, lambda *args: None)
    try:
        companion = speaking.get_companion_service()
    finally:
        for cached in (agent.get_learner_facts, agent.get_agent_memory, agent.get_context_builder):
            cached.cache_clear()  # nothing built on the stand-in client outlives this test
    assert isinstance(companion.target_catalog, SelectedTargetCatalog)
