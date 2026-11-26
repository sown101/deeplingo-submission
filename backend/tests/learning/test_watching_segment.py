"""FR-3.3: the agent knows which part of the video the learner is watching.

The client names a transcript segment; the server re-checks the whole chain
Library item -> video -> original transcript -> segment before it reaches the model.
"""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.learning.domain.companion import CompanionEntry
from tests.learning.test_companion import ITEM_ID, OTHER, USER, error_of, make_service
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, auth, service as relay_service,
)
import json

SEGMENT = uuid4()


def segment(sequence, text, transcript_id, *, segment_id=None, start=0):
    return SimpleNamespace(id=segment_id or uuid4(), transcript_id=transcript_id, sequence_number=sequence,
                           start_ms=start, end_ms=start + 3000, text=text)


def service_watching(*, same_transcript=True, found=True):
    service = make_service()
    transcript_id = service.transcripts.list_for_video.return_value[0].id
    owner_transcript = transcript_id if same_transcript else uuid4()
    current = segment(5, "I am afraid of heights.", owner_transcript, segment_id=SEGMENT, start=65_000)
    before = segment(4, "Flying is fun.", transcript_id, start=62_000)
    after = segment(6, "But take-off is scary.", transcript_id, start=68_000)
    service.segments.get_by_id.side_effect = lambda segment_id: current if found and segment_id == SEGMENT else None
    service.segments.get_neighbor.side_effect = lambda *, transcript_id, sequence_number, offset: (
        before if offset == -1 else after)
    return service, current, before, after


def test_the_ticket_names_the_part_being_watched_with_its_neighbours():
    service, *_ = service_watching()
    prepared = service.prepare(USER, CompanionEntry.VIDEO, ITEM_ID, SEGMENT)
    excerpt = prepared.ticket.excerpt
    assert "Playing now (01:05): I am afraid of heights." in excerpt
    assert "Flying is fun." in excerpt and "But take-off is scary." in excerpt
    assert excerpt.index("Flying is fun.") < excerpt.index("Playing now") < excerpt.index("But take-off is scary.")
    assert prepared.ticket.library_item_id == ITEM_ID


def test_offered_words_prefer_the_watched_part_and_fall_back_to_the_video():
    service, current, before, after = service_watching()
    service.prepare(USER, CompanionEntry.VIDEO, ITEM_ID, SEGMENT)
    assert service.catalog.calls[0]["segment_ids"] == {current.id, before.id, after.id}


def test_without_a_segment_nothing_changes():
    service, *_ = service_watching()
    prepared = service.prepare(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert "Playing now" not in (prepared.ticket.excerpt or "")
    service.segments.get_by_id.assert_not_called()


@pytest.mark.parametrize("kwargs", [{"same_transcript": False}, {"found": False}])
def test_a_segment_outside_this_videos_transcript_is_refused(kwargs):
    service, *_ = service_watching(**kwargs)
    assert error_of(lambda: service.prepare(USER, CompanionEntry.VIDEO, ITEM_ID, SEGMENT)) == (
        "not_found", "companion_segment_not_found")


def test_another_learners_library_item_is_refused_before_the_segment_is_read():
    service, *_ = service_watching()
    stranger = SimpleNamespace(id=OTHER)
    assert error_of(lambda: service.prepare(stranger, CompanionEntry.VIDEO, ITEM_ID, SEGMENT)) == (
        "not_found", "companion_video_not_found")
    service.segments.get_by_id.assert_not_called()


def test_a_segment_only_makes_sense_for_a_video_conversation():
    service, *_ = service_watching()
    assert error_of(lambda: service.prepare(USER, CompanionEntry.HOME, None, SEGMENT)) == (
        "invalid_input", "companion_selector_unexpected")


# --- Realtime start message -----------------------------------------------------------------

def run_start(extra):
    relay = relay_service(voice=FakeVoice())
    seen = {}
    real = relay.setup.prepare

    def spy(user, entry, library_item_id, segment_id=None, topic_id=None):
        seen["segment_id"] = segment_id
        return real(user, entry, library_item_id)

    relay.setup.prepare = spy
    start = ("text", json.dumps({"type": "start", "entry": "video", "library_item_id": str(ITEM_ID), **extra}))
    channel = FakeChannel([auth(), start])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())
    return seen, channel


def test_the_start_message_may_carry_the_segment_being_watched():
    seen, channel = run_start({"segment_id": str(SEGMENT)})
    assert str(seen["segment_id"]) == str(SEGMENT)
    assert "ready" in channel.types()


def test_a_start_message_without_a_segment_passes_none():
    seen, _ = run_start({})
    assert seen["segment_id"] is None


def test_a_malformed_segment_id_is_refused_before_any_provider_session():
    _, channel = run_start({"segment_id": "not-a-uuid"})
    assert channel.closed == 4400 and channel.json[-1]["code"] == "realtime_start_invalid"
