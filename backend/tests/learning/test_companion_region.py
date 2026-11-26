"""M1 S3: the companion talks about the learner's study region and may suggest one practice tool."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.bootstrap.wiring.speaking import _StudyRegions
from app.modules.learning.application.agent.prompts import AGENT_TEXT_PROMPT_VERSION, build_agent_system_prompt
from app.modules.learning.application.learned_items import LearnedItemCatalog
from app.modules.learning.domain.companion import (
    MAX_REGION_EXCERPT_CHARS,
    CompanionEntry,
    RegionLine,
    StudyRegionContext,
    render_region_excerpt,
)
from tests.learning.test_companion import (
    FLY,
    ITEM_ID,
    OWNER,
    USER,
    VIDEO_ID,
    error_of,
    make_service,
    speech,
    ticket,
    turn_output,
)

SEG_A, SEG_B = str(uuid4()), str(uuid4())
REGION = StudyRegionContext(
    lines=(RegionLine("s1", SEG_A, 8_000, 12_000, "I missed my train this morning."),
           RegionLine("s2", SEG_B, 12_000, 15_500, "So I ended up taking a taxi.")),
    before="It was raining a lot.", after="The taxi was expensive.",
)


def region_service(*, outputs=(turn_output(),), texts=(), region=REGION, reader=None, items=None,
                   video_status="ready"):
    service = make_service(outputs=outputs, texts=texts, video_status=video_status,
                           **({"items": items} if items is not None else {}))
    if reader is None:
        reader = Mock()
        reader.for_learner.return_value = region
    service.regions = reader
    return service


def suggestion(**overrides):
    data = {"tool": "dictation", "segment_ref": "s2", "reason_support": "Bạn nói chưa nghe rõ câu này."}
    data.update(overrides)
    return data


def test_a_study_region_is_the_conversation_context_as_delimited_lines():
    service = region_service()
    view = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)

    service.regions.for_learner.assert_called_once_with(OWNER, ITEM_ID)
    prompt = service.model.prompts[0]
    assert "<video_part>\n(before) It was raining a lot.\n[s1 00:08] I missed my train this morning." in prompt
    assert "[s2 00:12] So I ended up taking a taxi.\n(after) The taxi was expensive.\n</video_part>" in prompt
    assert "<excerpt>\n" not in prompt
    # Region items first.
    call = service.catalog.calls[0]
    assert call["segment_ids"] == {UUID(SEG_A), UUID(SEG_B)}
    lines = service.load(USER, view.session_ticket).ticket.region_lines
    assert [(line.ref, line.segment_id, line.start_ms, line.end_ms) for line in lines] == [
        ("s1", SEG_A, 8_000, 12_000), ("s2", SEG_B, 12_000, 15_500)]
    assert view.practice_suggestion is None


def test_a_suggestion_on_an_offered_line_is_shown_with_that_line_and_never_opens_anything():
    service = region_service(outputs=(turn_output(), turn_output(suggest_practice=suggestion())),
                             texts=["Sorry, I could not hear the second sentence"])
    first = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    view = service.turn(USER, first.session_ticket, speech())

    shown = view.practice_suggestion
    assert (shown.tool, str(shown.segment_id), shown.start_ms, shown.end_ms) == ("dictation", SEG_B, 12_000, 15_500)
    assert shown.reason == "Bạn nói chưa nghe rõ câu này."
    # The region still reaches the next turn through the stored conversation, without a re-read.
    service.regions.for_learner.assert_called_once()
    assert "[s2 00:12]" in service.model.prompts[1]
    assert "suggest_practice" in service.model.calls[1][1]  # offered on a turn, not on the opening
    assert service.load(USER, view.session_ticket).ticket.region_lines[1].segment_id == SEG_B


@pytest.mark.parametrize("bad", [suggestion(segment_ref="s9"), suggestion(reason_support="   ")])
def test_a_suggestion_outside_the_offered_region_is_dropped_but_the_turn_is_kept(bad):
    service = region_service(outputs=(turn_output(), turn_output(suggest_practice=bad)), texts=["I could not hear it"])
    view = service.turn(USER, service.start(USER, CompanionEntry.VIDEO, ITEM_ID).session_ticket, speech())
    assert view.practice_suggestion is None and view.reply == "Do you like flying?"


def test_without_a_region_the_video_start_is_delimited_data_and_suggestions_are_dropped():
    service = region_service(region=None, outputs=(turn_output(), turn_output(
        suggest_practice=suggestion(segment_ref="s1"))), texts=["I could not hear it"])
    first = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    view = service.turn(USER, first.session_ticket, speech())
    prompt = service.model.prompts[0]
    assert "<excerpt>\nI love flying. Airports are stressful.\n</excerpt>" in prompt
    assert "<video_part>\n" not in prompt
    assert view.practice_suggestion is None and service.load(USER, view.session_ticket).ticket.region_lines == ()


def test_a_region_read_failure_is_unavailable_and_never_talks_about_another_part():
    reader = Mock()
    reader.for_learner.side_effect = RuntimeError("database unavailable")
    service = region_service(reader=reader)
    assert error_of(lambda: service.start(USER, CompanionEntry.VIDEO, ITEM_ID)) == (
        "unavailable", "companion_region_unavailable")
    assert service.model.prompts == []


def test_a_chosen_part_is_enough_even_when_the_whole_video_is_not_prepared():
    service = region_service(video_status="failed")
    view = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert view.reply and "<video_part>" in service.model.prompts[0]
    no_part = region_service(region=None, video_status="failed")
    assert error_of(lambda: no_part.start(USER, CompanionEntry.VIDEO, ITEM_ID)) == (
        "conflict", "companion_video_not_ready")


def test_a_region_without_prepared_items_offers_the_video_items():
    service = region_service()
    service.catalog.for_learner = Mock(side_effect=[[], [FLY]])
    service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    first, second = service.catalog.for_learner.call_args_list
    assert "segment_ids" in first.kwargs and "segment_ids" not in second.kwargs
    assert "- fly |" in service.model.prompts[0]


def test_home_and_review_conversations_never_read_a_region():
    service = region_service()
    service.start(USER, CompanionEntry.HOME, None)
    service.regions.for_learner.assert_not_called()
    assert "<video_part>\n" not in service.model.prompts[0]


# --- Contract ---------------------------------------------------------------------------

def test_prompt_version_and_data_markers():
    from app.modules.learning.domain.companion import level_policy
    assert AGENT_TEXT_PROMPT_VERSION == "agent-text-v10"
    for region, marker in ((True, "<video_part>\n"), (False, "<excerpt>\n")):
        prompt = build_agent_system_prompt(
            learning_language="en", support_language="vi", policy=level_policy("en"), topic="t", mode="topic",
            items=[], excerpt="Some line.", region=region)
        assert marker in prompt


def test_a_suggestion_must_name_a_line_tool_and_reason_the_server_offered():
    """The strict JSON schema is gone: the registry's `suggest_practice` checks the same things on the call."""
    import asyncio
    from app.modules.learning.application.agent.session import AgentSession
    from app.modules.learning.application.agent.tools import ToolRegistry
    from app.modules.learning.application.agent.setup import PreparedConversation
    session = AgentSession(user=USER, prepared=PreparedConversation(ticket=ticket(region_lines=REGION.lines)))
    registry = ToolRegistry()
    for bad in (suggestion(tool="questions"), suggestion(segment_ref="seg-1"), suggestion(segment_ref="s123"),
                suggestion(reason_support="  ")):
        args = {"tool": bad["tool"], "segment_ref": bad["segment_ref"], "reason": bad["reason_support"]}
        assert asyncio.run(registry.call(session, "suggest_practice", args)).events == []
    good = asyncio.run(registry.call(session, "suggest_practice", {"tool": "shadowing", "segment_ref": "s1",
                                                                   "reason": "Luyện nhịp."}))
    assert good.events[0]["segment_id"] == SEG_A and "suggest_practice" not in {
        spec.name for spec in ToolRegistry.specs()}  # the voice channel does not declare it


def test_region_lines_round_trip_in_the_stored_conversation_without_their_text():
    from app.modules.learning.application.agent.conversation import TextSession, dump_state, load_state
    from app.modules.learning.application.agent.setup import PreparedConversation
    session = TextSession(user=USER, prepared=PreparedConversation(
        ticket=ticket(region_lines=REGION.lines, excerpt="x" * MAX_REGION_EXCERPT_CHARS)))
    read = load_state(dump_state(session), USER, session.id).ticket
    assert [(line.ref, line.segment_id, line.text) for line in read.region_lines] == [("s1", SEG_A, ""), ("s2", SEG_B, "")]
    assert len(read.excerpt) == MAX_REGION_EXCERPT_CHARS


def test_the_region_excerpt_is_bounded_and_keeps_refs_of_included_lines_only():
    long = StudyRegionContext(lines=tuple(RegionLine(f"s{i}", str(uuid4()), i * 1000, i * 1000 + 900, "word " * 60)
                                          for i in range(1, 41)), before="b " * 300, after="a")
    text, kept = render_region_excerpt(long)
    assert len(text) <= MAX_REGION_EXCERPT_CHARS and 0 < len(kept) < 40
    assert all(f"[{line.ref} " in text for line in kept) and f"[s{len(kept) + 1} " not in text


# --- Adapter and catalog ------------------------------------------------------------------

def _adapter(*, owned=True, region=(2, 3), transcript_matches=True, count=6):
    track_id = uuid4()
    rows = [SimpleNamespace(id=uuid4(), sequence_number=i, start_ms=i * 1000, end_ms=i * 1000 + 900, text=f"Line {i}")
            for i in range(1, count + 1)]
    library, workspaces, videos, transcripts, segments = Mock(), Mock(), Mock(), Mock(), Mock()
    library.get_for_user.return_value = SimpleNamespace(video_id=VIDEO_ID) if owned else None
    workspaces.get_for_user.return_value = SimpleNamespace(
        region_transcript_id=track_id if transcript_matches else uuid4(),
        region_start_segment_id=rows[region[0] - 1].id, region_end_segment_id=rows[region[1] - 1].id)
    videos.get_by_id.return_value = SimpleNamespace(id=VIDEO_ID, original_language_code="en")
    transcripts.list_for_video.return_value = [SimpleNamespace(id=track_id, is_original=True, language_code="en")]
    segments.list_for_transcript.return_value = list(reversed(rows))
    return _StudyRegions(workspaces=workspaces, library=library, videos=videos, transcripts=transcripts,
                         segments=segments), rows


def test_the_adapter_returns_the_saved_region_with_neighbors():
    adapter, rows = _adapter()
    context = adapter.for_learner(OWNER, ITEM_ID)
    assert [(line.ref, line.segment_id, line.text) for line in context.lines] == [
        ("s1", str(rows[1].id), "Line 2"), ("s2", str(rows[2].id), "Line 3")]
    assert (context.before, context.after) == ("Line 1", "Line 4")


@pytest.mark.parametrize("kwargs", [dict(owned=False), dict(transcript_matches=False), dict(region=(4, 2)),
                                    dict(region=(1, 45), count=50)])
def test_the_adapter_returns_nothing_for_a_foreign_stale_or_invalid_region(kwargs):
    adapter, _ = _adapter(**kwargs)
    assert adapter.for_learner(OWNER, ITEM_ID) is None


def test_the_catalog_can_keep_only_region_occurrences():
    video = SimpleNamespace(id=uuid4(), original_language_code="en", learning_status="ready")
    inside, outside, kept_concept = uuid4(), uuid4(), uuid4()
    objects, concepts = Mock(), Mock()
    objects.list_for_videos.return_value = [
        SimpleNamespace(video_id=video.id, concept_id=uuid4(), transcript_segment_id=outside, evidence_text="far",
                        raw_ai_diagnostics=None),
        SimpleNamespace(video_id=video.id, concept_id=kept_concept, transcript_segment_id=inside,
                        evidence_text="ended up", raw_ai_diagnostics=None)]
    concepts.list_by_ids.side_effect = lambda ids: [SimpleNamespace(
        id=concept_id, language_code="en", sense_key="k", canonical_text="end up", type="expression")
        for concept_id in ids]
    catalog = LearnedItemCatalog(library=Mock(), videos=Mock(), learning_objects=objects, concepts=concepts)
    items = catalog.for_learner(OWNER, language_code="en", support_language_code="vi", owned_videos=[video],
                                segment_ids={inside})
    assert [(item.concept_id, item.source) for item in items] == [(str(kept_concept), "from_video")]
    assert concepts.list_by_ids.call_args.args[0] == [kept_concept]


# --- M1 S7b: the real catalog with the service ------------------------------------------------

def real_catalog(occurrences):
    from app.modules.content.contracts import Concept, ConceptType
    taxi = Concept(id=uuid4(), language_code="en", type=ConceptType.PHRASAL_VERB, canonical_text="end up",
                   normalized_text="end up", sense_key="to finally be")
    objects, concepts = Mock(), Mock()
    objects.list_for_videos.side_effect = lambda ids: [
        SimpleNamespace(video_id=VIDEO_ID, concept_id=taxi.id, transcript_segment_id=UUID(segment),
                        evidence_text="ended up", raw_ai_diagnostics=None)
        for segment in occurrences] if VIDEO_ID in ids else []
    concepts.list_by_ids.side_effect = lambda ids: [taxi] if taxi.id in ids else []
    return LearnedItemCatalog(library=Mock(), videos=Mock(), learning_objects=objects, concepts=concepts), taxi


def test_a_prepared_part_is_enough_with_the_real_catalog_when_the_video_is_not_ready():
    service = region_service(video_status="processing")
    service.catalog, taxi = real_catalog([SEG_B])
    view = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert view.reply and "- end up |" in service.model.prompts[0]


def test_with_the_real_catalog_an_unprepared_part_of_an_unready_video_has_nothing_to_offer():
    service = region_service(video_status="processing")
    service.catalog, _ = real_catalog([str(uuid4())])  # the only occurrence is outside the part
    assert error_of(lambda: service.start(USER, CompanionEntry.VIDEO, ITEM_ID)) == ("conflict", "companion_no_items")
    no_part = region_service(region=None, video_status="processing")
    no_part.catalog, _ = real_catalog([SEG_B])
    assert error_of(lambda: no_part.start(USER, CompanionEntry.VIDEO, ITEM_ID)) == (
        "conflict", "companion_video_not_ready")
