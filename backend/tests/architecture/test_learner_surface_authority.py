"""Beta-0 / A13: learner API surface closure and composition-root contract.

Ordinary learners may submit learner-owned input only. Proof/diagnostic routes
that accepted server-authoritative GeneratedActivity payloads, ran learner-
triggered LLM generation or exposed raw planner/review-candidate internals are
unmounted. These tests fail if any learner route appears or disappears without
an explicit update to the canonical allowlist below.
"""
import ast
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_learner_model_service
from app.modules.identity.contracts import CurrentUser
from app.main import app

PREFIX = "/api/v1/v3"
USER_A = UUID("00000000-0000-0000-0000-00000000000a")

# Canonical Product V1 learner surface (method, path) after Beta-0.
LEARNER_ROUTE_ALLOWLIST = {
    ("POST", "/learner/me/library/videos/{library_item_id}/grammar-explanations"),
    ("GET", "/learner/me/language-profile"),
    ("PUT", "/learner/me/language-profile"),
    ("POST", "/learner/me/initialize"),
    ("GET", "/learner/me/library/videos"),
    ("POST", "/learner/me/library/videos"),
    ("GET", "/learner/me/library/videos/{library_item_id}"),
    ("POST", "/learner/me/library/videos/{library_item_id}/retry"),
    ("POST", "/learner/me/library/videos/{library_item_id}/learning/retry"),
    ("GET", "/learner/me/library/videos/{library_item_id}/playback"),
    ("GET", "/learner/me/library/videos/{library_item_id}/transcript"),
    ("GET", "/learner/me/library/videos/{library_item_id}/workspace"),
    # 2026-11-05: study parts cut by AI once per transcript (shared content); the client sends only a Library item id.
    ("GET", "/learner/me/library/videos/{library_item_id}/parts"),
    ("PUT", "/learner/me/library/videos/{library_item_id}/workspace/position"),
    ("PUT", "/learner/me/library/videos/{library_item_id}/workspace/region"),

    # M1 S4: practice log (selectors and raw Dictation input; practice only).
    ("POST", "/learner/me/library/videos/{library_item_id}/practice-events/dictation"),
    ("POST", "/learner/me/library/videos/{library_item_id}/practice-events/lookup"),
    ("GET", "/learner/me/library/videos/{library_item_id}/region-questions"),
    ("POST", "/learner/me/library/videos/{library_item_id}/region-questions/{question_id}/answer"),
    # Phase 3 (2026-11-14): bilingual subtitles and the result card of a study region.
    ("POST", "/learner/me/library/videos/{library_item_id}/translations"),
    ("GET", "/learner/me/library/videos/{library_item_id}/regions/{region}/result"),
    ("GET", "/learner/me/library/videos/{library_item_id}/learning-objects/{learning_object_id}/concept"),
    # Non-evidential speaking practice (raw audio + selectors only).
    ("POST", "/learner/me/library/videos/{library_item_id}/shadowing/assessments"),
    # Non-evidential voice companion (raw audio + signed session ticket only).
    ("GET", "/learner/me/speaking-sessions/{session_id}"),
    ("POST", "/learner/me/companion/sessions"),
    ("GET", "/learner/me/companion/scenarios"),
    ("POST", "/learner/me/companion/turns"),
    ("POST", "/learner/me/companion/turns/stream"),  # the same turn, its speech sentence by sentence
    ("POST", "/learner/me/companion/finish"),
    # Agent voice consent and personalization signals (closed codes only; no text from the client).
    ("GET", "/learner/me/agent/consent"),
    ("PUT", "/learner/me/agent/consent"),
    ("GET", "/learner/me/agent/signals"),
    ("DELETE", "/learner/me/agent/signals/{signal_id}"),
    ("DELETE", "/learner/me/agent/signals"),
    # FR-3.11 (2026-11-07): separate transcript consent; the learner lists and deletes their kept turns.
    ("GET", "/learner/me/agent/transcripts/consent"),
    ("PUT", "/learner/me/agent/transcripts/consent"),
    ("GET", "/learner/me/agent/transcripts"),
    ("DELETE", "/learner/me/agent/transcripts/{transcript_id}"),
    ("DELETE", "/learner/me/agent/transcripts"),
    # Agent v2 phase 3 (PRD 8.12 point 3): what the agent remembers; the learner lists it and deletes (no writes).
    ("GET", "/learner/me/agent/memory"),
    ("DELETE", "/learner/me/agent/memory/{memory_id}"),
    ("DELETE", "/learner/me/agent/memory"),
    ("POST", "/learner/me/account/delete"),
    ("GET", "/learner/me/export"),
    # Daily study plan (local date and a choice per proposal only).
    ("GET", "/learner/me/plan"),
    ("POST", "/learner/me/plan/items/{item_id}/accept"),
    ("POST", "/learner/me/plan/items/{item_id}/dismiss"),
    # Agent v2 phase 4 (PRD 8.12 point 4): undo of one task the agent added or removed (a choice only).
    ("POST", "/learner/me/plan/items/{item_id}/undo"),
    # Restructure phase 1: the learner's own learning log and study requests (filters and a dismiss only).
    # Restructure phase 5: progress of the signed-in learner (language filter and display offset only).
    ("GET", "/learner/me/progress"),
    ("GET", "/learner/me/agent/study-requests"),
    ("POST", "/learner/me/study-requests/{request_id}/dismiss"),
    # Read-only meaning of any selected word or phrase in an owned transcript.
    ("POST", "/learner/me/library/videos/{library_item_id}/lookup"),
    # My words (server-resolved Concepts; saved = priority request only).
    ("GET", "/learner/me/words"),
    ("POST", "/learner/me/words"),
    ("DELETE", "/learner/me/words/{concept_id}"),
    ("PUT", "/learner/me/words/{concept_id}/status"),  # L1a: the learner's own choice for a target
    # L1b: private named lists, bulk import (the server resolves every word) and the choice of a meaning.
    ("POST", "/learner/me/lists"),
    ("GET", "/learner/me/lists"),
    ("GET", "/learner/me/lists/{list_id}"),
    ("DELETE", "/learner/me/lists/{list_id}"),
    ("POST", "/learner/me/lists/{list_id}/import"),
    ("PUT", "/learner/me/lists/{list_id}/lines/{line_id}"),
    ("DELETE", "/learner/me/lists/{list_id}/lines/{line_id}"),
    ("PUT", "/learner/me/lists/{list_id}/words/{concept_id}"),
    ("DELETE", "/learner/me/lists/{list_id}/words/{concept_id}"),
    # Notebook redesign: the learner's own marks, a memory rating that moves the schedule only, read-only
    # reference data, and words read aloud or assessed only if the dictionary holds them.
    ("PUT", "/learner/me/words/{concept_id}/personal"),
    ("POST", "/learner/me/words/{concept_id}/memory-rating"),
    ("GET", "/learner/me/words/{concept_id}/details"),
    ("POST", "/learner/me/words/images"),
    ("GET", "/learner/me/word-sets"),
    ("GET", "/learner/me/word-sets/{key}"),
    ("POST", "/learner/me/lists/{list_id}/from-set"),
    ("GET", "/learner/me/dictionary/audio"),
    ("POST", "/learner/me/dictionary/pronunciation"),
    # L1c: lexical coverage of the learner's own videos; the client sends only a Library item id.
    ("GET", "/learner/me/video-coverage"),
    ("GET", "/learner/me/dictionary/search"),
    ("GET", "/learner/me/words/{concept_id}/examples"),
    ("POST", "/learner/me/words/{concept_id}/examples"),
    # Restructure phase 2: review decks per language and grammar in the notebook (selectors and learner input only;
    # the server grades, schedules and logs).
    ("GET", "/learner/me/review/decks"),
    ("GET", "/learner/me/review/{language}/due"),
    ("POST", "/learner/me/review/answers"),
    ("POST", "/learner/me/review/answers/pronunciation"),
    ("GET", "/learner/me/review/cards/{concept_id}/audio"),
    ("GET", "/learner/me/words/{concept_id}/pronunciation"),
    ("GET", "/learner/me/grammar/{language}"),
    ("GET", "/learner/me/grammar/{language}/exercises"),
    ("POST", "/learner/me/grammar/answers"),
    ("POST", "/learner/me/grammar/lessons"),
}
# Backend calls made by the active clients' API adapters
# (deeplingo_web/src/features/**/*Api.ts).
CLIENT_CONTRACT = {
    ("POST", "/learner/me/library/videos/{library_item_id}/grammar-explanations"),
    ("GET", "/languages"),
    ("GET", "/learner/me/language-profile"),
    ("PUT", "/learner/me/language-profile"),
    ("POST", "/learner/me/initialize"),
    ("GET", "/learner/me/library/videos"),
    ("POST", "/learner/me/library/videos"),
    ("GET", "/learner/me/library/videos/{library_item_id}"),
    ("POST", "/learner/me/library/videos/{library_item_id}/retry"),
    ("POST", "/learner/me/library/videos/{library_item_id}/learning/retry"),
    ("GET", "/learner/me/library/videos/{library_item_id}/playback"),
    ("GET", "/learner/me/library/videos/{library_item_id}/transcript"),
    ("GET", "/learner/me/library/videos/{library_item_id}/workspace"),
    ("PUT", "/learner/me/library/videos/{library_item_id}/workspace/position"),
    ("PUT", "/learner/me/library/videos/{library_item_id}/workspace/region"),

    # M1 S4: practice log (selectors and raw Dictation input; practice only).
    ("POST", "/learner/me/library/videos/{library_item_id}/practice-events/dictation"),
    ("POST", "/learner/me/library/videos/{library_item_id}/practice-events/lookup"),
    ("GET", "/learner/me/library/videos/{library_item_id}/region-questions"),
    ("POST", "/learner/me/library/videos/{library_item_id}/region-questions/{question_id}/answer"),
    # Phase 3 (2026-11-14): bilingual subtitles and the result card of a study region.
    ("POST", "/learner/me/library/videos/{library_item_id}/translations"),
    ("GET", "/learner/me/library/videos/{library_item_id}/regions/{region}/result"),
    ("GET", "/learner/me/library/videos/{library_item_id}/learning-objects/{learning_object_id}/concept"),
    # Non-evidential speaking practice (raw audio + selectors only).
    ("POST", "/learner/me/library/videos/{library_item_id}/shadowing/assessments"),
    ("POST", "/learner/me/companion/sessions"),
    ("POST", "/learner/me/companion/turns"),
    ("POST", "/learner/me/companion/turns/stream"),  # the same turn, its speech sentence by sentence
    ("POST", "/learner/me/companion/finish"),
    ("POST", "/learner/me/account/delete"),
    ("GET", "/learner/me/export"),
    ("GET", "/learner/me/plan"),
    ("POST", "/learner/me/plan/items/{item_id}/accept"),
    ("POST", "/learner/me/plan/items/{item_id}/dismiss"),
    ("POST", "/learner/me/plan/items/{item_id}/undo"),
    # What the agent remembers (phase 3): the Profile lists it and deletes it.
    ("GET", "/learner/me/agent/study-requests"),
    ("POST", "/learner/me/study-requests/{request_id}/dismiss"),
    ("GET", "/learner/me/agent/memory"),
    ("DELETE", "/learner/me/agent/memory/{memory_id}"),
    ("DELETE", "/learner/me/agent/memory"),
    # Read-only meaning of any selected word or phrase in an owned transcript.
    ("POST", "/learner/me/library/videos/{library_item_id}/lookup"),
    # My words (server-resolved Concepts; saved = priority request only).
    ("GET", "/learner/me/words"),
    ("POST", "/learner/me/words"),
    ("DELETE", "/learner/me/words/{concept_id}"),
    ("PUT", "/learner/me/words/{concept_id}/status"),  # L1a: the learner's own choice for a target
    # L1b: private named lists, bulk import (the server resolves every word) and the choice of a meaning.
    ("POST", "/learner/me/lists"),
    ("GET", "/learner/me/lists"),
    ("GET", "/learner/me/lists/{list_id}"),
    ("DELETE", "/learner/me/lists/{list_id}"),
    ("POST", "/learner/me/lists/{list_id}/import"),
    ("PUT", "/learner/me/lists/{list_id}/lines/{line_id}"),
    ("DELETE", "/learner/me/lists/{list_id}/lines/{line_id}"),
    ("PUT", "/learner/me/lists/{list_id}/words/{concept_id}"),
    ("DELETE", "/learner/me/lists/{list_id}/words/{concept_id}"),
    # Notebook redesign: the learner's own marks, a memory rating that moves the schedule only, read-only
    # reference data, and words read aloud or assessed only if the dictionary holds them.
    ("PUT", "/learner/me/words/{concept_id}/personal"),
    ("POST", "/learner/me/words/{concept_id}/memory-rating"),
    ("GET", "/learner/me/words/{concept_id}/details"),
    ("POST", "/learner/me/words/images"),
    ("GET", "/learner/me/word-sets"),
    ("GET", "/learner/me/word-sets/{key}"),
    ("POST", "/learner/me/lists/{list_id}/from-set"),
    ("GET", "/learner/me/dictionary/audio"),
    ("POST", "/learner/me/dictionary/pronunciation"),
    # L1c: lexical coverage of the learner's own videos; the client sends only a Library item id.
    ("GET", "/learner/me/video-coverage"),
    ("GET", "/learner/me/dictionary/search"),
    ("GET", "/learner/me/words/{concept_id}/examples"),
    ("POST", "/learner/me/words/{concept_id}/examples"),
    # Restructure phase 2: review decks per language and grammar in the notebook (selectors and learner input only;
    # the server grades, schedules and logs).
    ("GET", "/learner/me/review/decks"),
    ("GET", "/learner/me/review/{language}/due"),
    ("POST", "/learner/me/review/answers"),
    ("POST", "/learner/me/review/answers/pronunciation"),
    ("GET", "/learner/me/review/cards/{concept_id}/audio"),
    ("GET", "/learner/me/words/{concept_id}/pronunciation"),
    ("GET", "/learner/me/grammar/{language}"),
    ("GET", "/learner/me/grammar/{language}/exercises"),
    ("POST", "/learner/me/grammar/answers"),
    ("POST", "/learner/me/grammar/lessons"),
}
_ID = "00000000-0000-0000-0000-000000000001"
REMOVED_ROUTES = [
    # Restructure phase 2: example practice, replaced by the review engine (no client called it).
    ("POST", f"/learner/me/words/{_ID}/practice"),
    ("GET", f"/learner/me/relevance/learning-objects/{_ID}"),
    ("GET", "/learner/me/planner/context"),
    ("GET", f"/learner/me/planner/candidates/{_ID}"),
    ("GET", f"/learner/me/planner/eligibility/{_ID}"),
    ("GET", f"/learner/me/planner/scoring/{_ID}"),
    ("GET", f"/learner/me/planner/ordering/{_ID}"),
    ("POST", f"/learner/me/planner/sessions/{_ID}"),
    ("GET", f"/learner/me/session-activities/{_ID}/generation"),
    ("POST", f"/learner/me/session-activities/{_ID}/generate"),
    ("POST", f"/learner/me/session-activities/{_ID}/validate"),
    ("POST", f"/learner/me/session-activities/{_ID}/persist"),
    ("GET", "/learner/me/review-candidates"),
    ("POST", f"/learner/me/session-activities/{_ID}/attempts"),
    ("POST", f"/learner/me/attempts/{_ID}/assess"),
    # B3 (2026-10-26): the old review session, the planner-based video practice start, mastery and skill states.
    ("GET", "/learner/me/review-queue"),
    ("POST", "/learner/me/review-sessions"),
    ("GET", f"/learner/me/review-sessions/{_ID}"),
    ("GET", f"/learner/me/review-sessions/{_ID}/next"),
    ("POST", f"/learner/me/library/videos/{_ID}/learning-sessions"),
    ("GET", "/learner/me/skills"),
    ("GET", "/learner/me/mastery-summary"),
    ("GET", "/learner/me/review-candidates/eligibility"),
    ("GET", "/learner/me/review-candidates/scoring"),
    ("GET", "/learner/me/review-candidates/selection"),
    ("GET", f"/learner/me/review-candidates/{_ID}/concept_to_meaning/eligibility"),
    ("GET", f"/learner/me/review-candidates/{_ID}/concept_to_meaning/scoring"),
    ("GET", f"/learner/me/review-candidates/{_ID}/concept_to_meaning/context"),
    ("GET", f"/learner/me/review-candidates/{_ID}/concept_to_meaning/activity-plan"),
    ("POST", f"/learner/me/review-candidates/{_ID}/concept_to_meaning/materialize"),
]

# A learner-authored activity with a self-chosen answer key: the A13 payload.
FORGED_ACTIVITY = {
    "generated_activity": {
        "session_activity_id": _ID,
        "activity_type": "mcq",
        "prompt_payload": {"question": "q", "options": ["a", "b", "c", "d"]},
        "expected_response_payload": {"correct_option": 3},
        "provenance": {"generation_strategy": "ai"},
        "generation_strategy": "ai",
        "generation_version": "forged",
        "status": "generated",
    }
}

AUTHORITY_FIELDS = {
    "expected_response_payload", "generated_activity", "validated_activity",
    "prompt_payload", "provenance", "generation_strategy", "correct_option",
    "expected_answer", "review_rating", "fsrs_state",
}


class AuthVerifier:
    def verify(self, token: str) -> CurrentUser:
        return CurrentUser(id=USER_A)


def _learner_routes() -> set[tuple[str, str]]:
    routes = set()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith(f"{PREFIX}/learner/"):
            for method in route.methods:
                routes.add((method, route.path.removeprefix(PREFIX)))
    return routes


def _all_v3_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path.removeprefix(PREFIX))
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(PREFIX)
        for method in route.methods
    }


def test_learner_surface_matches_canonical_product_allowlist():
    assert _learner_routes() == LEARNER_ROUTE_ALLOWLIST


def test_every_active_client_call_remains_mounted():
    missing = CLIENT_CONTRACT - _all_v3_routes()
    assert not missing


def test_removed_proof_routes_are_unmounted_even_for_authenticated_learner():
    app.dependency_overrides[get_jwt_verifier] = lambda: AuthVerifier()
    try:
        client = TestClient(app)
        for method, path in REMOVED_ROUTES:
            response = client.request(
                method, PREFIX + path, json=FORGED_ACTIVITY if method == "POST" else None,
                headers={"Authorization": "Bearer a.b.c"},
            )
            assert response.status_code == 404, (method, path, response.status_code)
    finally:
        app.dependency_overrides.clear()


def test_learner_cannot_persist_forged_generated_activity_without_auth_either():
    response = TestClient(app).post(
        f"{PREFIX}/learner/me/session-activities/{uuid4()}/persist", json=FORGED_ACTIVITY,
    )
    assert response.status_code == 404


def test_openapi_exposes_no_proof_paths_or_authority_bearing_learner_bodies():
    spec = app.openapi()
    for path in spec["paths"]:
        for fragment in ("/planner/", "/review-candidates", "/relevance/", "/generation", "/generate", "/validate", "/persist"):
            assert fragment not in path, path

    schemas = spec.get("components", {}).get("schemas", {})

    def properties(schema, seen):
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[-1]
            if name in seen:
                return set()
            seen.add(name)
            schema = schemas[name]
        names = set(schema.get("properties", {}))
        for child in [*schema.get("properties", {}).values(), *schema.get("anyOf", []), *schema.get("allOf", []), schema.get("items")]:
            if isinstance(child, dict) and child:
                names |= properties(child, seen)
        return names

    for path, operations in spec["paths"].items():
        if not path.startswith(f"{PREFIX}/learner/"):
            continue
        for operation in operations.values():
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if body:
                assert not properties(body, set()) & AUTHORITY_FIELDS, path


def test_module_api_layers_define_no_dependency_providers():
    # Providers live only in bootstrap.wiring; routers reference them.
    for path in Path("app/modules").rglob("api/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        providers = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name.startswith("get_") and not node.decorator_list]
        assert not providers, (path, providers)


def test_bootstrap_dependency_override_reaches_product_route():
    from app.modules.learner.application.views import LearnerLanguageProfile

    class FakeLearnerModel:
        def get_language_profile(self, current_user):
            assert current_user.id == USER_A
            return LearnerLanguageProfile(learning_language="en", support_language="vi", is_complete=True)

    app.dependency_overrides[get_jwt_verifier] = lambda: AuthVerifier()
    app.dependency_overrides[get_learner_model_service] = lambda: FakeLearnerModel()
    try:
        response = TestClient(app).get(f"{PREFIX}/learner/me/language-profile", headers={"Authorization": "Bearer a.b.c"})
        assert response.status_code == 200
        assert response.json()["learning_language"] == "en"
    finally:
        app.dependency_overrides.clear()


def _imports(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_routers_do_not_import_other_routers():
    # Only identity's FastAPI auth dependencies are shared between API layers.
    for path in Path("app/modules").rglob("api/*.py"):
        own = f"app.modules.{path.parts[2]}.api"
        for module in _imports(path):
            if module.startswith("app.modules.") and ".api" in module and not module.startswith(own):
                assert module == "app.modules.identity.api.dependencies", (path, module)


def test_inner_layers_do_not_import_composition_root():
    for package in ("app/platform", "app/kernel", "app/modules"):
        for path in Path(package).rglob("*.py"):
            # Module api/worker entrypoints may import bootstrap.wiring providers.
            if package == "app/modules" and {"api", "worker"} & set(path.parts):
                continue
            assert not any(module.startswith("app.bootstrap") for module in _imports(path)), path
