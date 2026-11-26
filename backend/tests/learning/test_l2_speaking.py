import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.learning.application.learned_items import LearnedItem
from app.modules.learning.application.selected_targets import SelectedTargetCatalog
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.domain.companion import CompanionEntry
from tests.learning.test_companion import make_service, OWNER, ITEM_ID, USER
from tests.learning.test_realtime_companion import service, FakeChannel, auth, TranscriptPiece, TurnComplete


FIRST, SECOND = uuid4(), uuid4()


def catalog(statuses=("active", "backlog")):
    targets = Mock()
    targets.list_for_user.return_value = [{"concept_id": str(cid), "status": state}
                                          for cid, state in zip((FIRST, SECOND), statuses)]
    concepts = Mock()
    concepts.list_by_ids.return_value = [SimpleNamespace(id=cid, language_code="en", canonical_text=text,
                                                        metadata={}, type="vocabulary")
                                        for cid, text in ((FIRST, "airport"), (SECOND, "travel"))]
    meanings, occurrences = Mock(), Mock()
    meanings.for_senses.return_value = {}
    occurrences.sentences_for.return_value = {}
    return SelectedTargetCatalog(targets=targets, concepts=concepts,
                                  meanings=meanings, occurrences=occurrences)


def select(reader, ids):
    return reader.select(OWNER, ids, language_code="en", support_language_code="vi")


def test_backlog_is_allowed_only_as_an_explicit_owned_selection_and_keeps_its_order():
    reader = catalog()
    items = select(reader, [SECOND, FIRST])
    assert [item.concept_id for item in items] == [str(SECOND), str(FIRST)]
    reader.targets.list_for_user.assert_called_once_with(OWNER, language_code="en")
    reader.targets.save.assert_not_called()
    reader.targets.set_status.assert_not_called()


@pytest.mark.parametrize("ids", [[], [FIRST, FIRST], [uuid4() for _ in range(13)]])
def test_bad_selection_is_rejected_before_content_reads(ids):
    reader = catalog()
    with pytest.raises(SpeakingPracticeError) as exc:
        select(reader, ids)
    assert exc.value.code == "companion_targets_invalid"
    reader.targets.list_for_user.assert_not_called()


@pytest.mark.parametrize("statuses,ids", [
    (("active", "backlog"), [uuid4()]),
    (("active", "suspended"), [SECOND]),
])
def test_other_learners_and_paused_words_are_not_offered(statuses, ids):
    reader = catalog(statuses)
    with pytest.raises(SpeakingPracticeError) as exc:
        select(reader, ids)
    assert exc.value.code == "companion_targets_unavailable"
    reader.meanings.for_senses.assert_not_called()
    reader.occurrences.sentences_for.assert_not_called()


def test_another_learning_language_is_rejected():
    reader = catalog()
    reader.concepts.list_by_ids.return_value[0].language_code = "zh"
    with pytest.raises(SpeakingPracticeError):
        select(reader, [FIRST, SECOND])


def test_cached_meaning_and_owned_video_form_are_used_without_a_model():
    reader = catalog()
    entry = uuid4()
    reader.concepts.list_by_ids.return_value = [SimpleNamespace(
        id=FIRST, language_code="en", canonical_text="travel", type="vocabulary",
        metadata={"dictionary_entry_id": str(entry), "dictionary_sense_id": "sense1"})]
    reader.meanings.for_senses.return_value = {(entry, "sense1"): {"meaning": "di chuyển"}}
    reader.occurrences.sentences_for.return_value = {FIRST: SimpleNamespace(target_form="travelling", meaning="đi lại")}
    item, = select(reader, [FIRST])
    assert item.meaning == "di chuyển" and item.forms == ("travel", "travelling")
    reader.occurrences.sentences_for.assert_called_once_with(OWNER, [FIRST], support_language_code="vi")


def test_selected_words_work_without_any_video_and_do_not_read_the_legacy_catalog():
    companion = make_service()
    companion.target_catalog = Mock()
    companion.target_catalog.select.return_value = [LearnedItem(str(SECOND), "travel", "vocabulary", None,
                                                               "selected", ("travel",))]
    prepared = companion.prepare_selected(USER, CompanionEntry.HOME, None, [SECOND])
    assert [item.item_id for item in prepared.ticket.items] == [str(SECOND)]
    assert companion.catalog.calls == []
    assert companion.model.prompts == []


def test_video_context_is_owned_and_keeps_explicit_sense_identities():
    companion = make_service()
    companion.target_catalog = Mock()
    companion.target_catalog.select.return_value = [LearnedItem(str(cid), "bank", "vocabulary", meaning,
                                                               "selected", ("bank",))
                                                   for cid, meaning in ((FIRST, "river"), (SECOND, "money"))]
    prepared = companion.prepare_selected(USER, CompanionEntry.VIDEO, ITEM_ID, [FIRST, SECOND])
    assert [item.item_id for item in prepared.ticket.items] == [str(FIRST), str(SECOND)]
    assert "I love flying." in prepared.ticket.excerpt
    with pytest.raises(SpeakingPracticeError):
        companion.prepare_selected(USER, CompanionEntry.VIDEO, uuid4(), [FIRST])


def test_relay_practises_the_words_the_agent_chose_without_writing_followups():
    async def scenario():
        relay = service()
        relay.setup.target_catalog = Mock()
        relay.setup.target_catalog.select.return_value = [LearnedItem(str(SECOND), "travel", "vocabulary",
                                                                         None, "selected", ("travel",))]
        relay.setup.end_conversation = Mock(side_effect=AssertionError("must stay in session"))
        relay.setup.focus = Mock()
        relay.setup.focus.choose.return_value = SimpleNamespace(
            title="Travel", topic_id=None,
            items=relay.setup.target_catalog.select.return_value)
        channel = FakeChannel([auth(), ("text", '{"type":"start","entry":"home"}')])
        task = asyncio.create_task(relay.run(channel))
        for _ in range(100):
            if relay.voice.opened:
                break
            await asyncio.sleep(.01)
        assert relay.voice.opened
        await relay.voice.connection.events_queue.put(TranscriptPiece("learner", "I travel often."))
        await relay.voice.connection.events_queue.put(TranscriptPiece("companion", "Where do you travel?"))
        await relay.voice.connection.events_queue.put(TurnComplete())
        await channel.inbound.put(("text", '{"type":"end"}'))
        await asyncio.wait_for(task, 2)
        relay.setup.target_catalog.select.assert_called_once_with(OWNER, [SECOND], language_code="en",
                                                                     support_language_code="vi")
        relay.setup.end_conversation.assert_not_called()
        ended = next(row for row in channel.json if row["type"] == "ended")
        assert "remembered" not in ended and ended["follow_ups"] == []
    asyncio.run(scenario())


def test_a_topic_that_is_not_the_learners_is_refused_before_opening_gemini_live():
    relay = service()
    relay.setup.focus = Mock()
    relay.setup.focus.choose.side_effect = SpeakingPracticeError(
        "not_found", "companion_topic_not_found", "That topic was not found.")
    channel = FakeChannel([auth(), ("text", json.dumps({"type": "start", "entry": "home", "topic_id": str(uuid4())}))])
    asyncio.run(relay.run(channel))
    assert relay.voice.opened == []
    assert channel.json[-1]["code"] == "companion_topic_not_found"
