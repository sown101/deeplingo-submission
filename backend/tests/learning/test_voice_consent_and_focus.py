"""FR-3.4 and FR-3.1: the server enforces the stored voice consent, and the agent, not the learner,
picks the focus words: due words of one topic, at most twelve."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.learning.application.focus_words import FocusWordChooser
from app.modules.learning.application.learned_items import LearnedItem
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.domain.companion import CompanionEntry
from tests.learning.test_companion import ITEM_ID, OWNER, USER, make_service
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, TranscriptPiece, TurnComplete, auth, service as relay_service, start,
)


class Consent:
    def __init__(self, granted=True):
        self.granted, self.asked = granted, []

    def has_consent(self, user_id):
        self.asked.append(user_id)
        return self.granted


def run(relay, inbound, steps=()):
    channel = FakeChannel(inbound)

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for step in steps:
            await step(relay, channel)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 3)

    asyncio.run(scenario())
    return channel


def test_without_a_granted_consent_no_provider_session_is_opened():
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.consent = Consent(False)
    channel = FakeChannel([auth(), start()])
    asyncio.run(relay.run(channel))
    assert channel.closed == 4403 and channel.json[-1]["code"] == "voice_consent_required"
    assert voice.opened == [] and relay.consent.asked == [OWNER]


def test_with_a_granted_consent_the_conversation_opens():
    relay = relay_service()
    relay.consent = Consent(True)
    channel = run(relay, [auth(), start()])
    assert "ready" in channel.types()


@pytest.mark.parametrize("field", ["analyze_session", "target_concept_ids"])
def test_the_old_per_session_consent_and_learner_chosen_words_are_no_longer_part_of_the_start_message(field):
    relay = relay_service(voice=FakeVoice())
    value = True if field == "analyze_session" else [str(uuid4())]
    channel = FakeChannel([auth(), ("text", json.dumps({"type": "start", "entry": "home", field: value}))])
    asyncio.run(relay.run(channel))
    assert channel.closed == 4400 and channel.json[-1]["code"] == "realtime_start_invalid"


def test_a_consent_revoked_during_the_conversation_stops_analysis_scoring_and_remembering():
    relay = relay_service()
    consent = Consent(True)
    relay.consent = consent
    processor, assessor, errors = Mock(), Mock(), Mock()
    relay.session_events, relay.pronunciation, relay.signals = processor, assessor, errors
    assessor.supports.return_value = True
    errors.recurring.return_value = []

    async def talk(relay, channel):
        await relay.voice.connection.events_queue.put(TranscriptPiece("learner", "I like to fly."))
        await relay.voice.connection.events_queue.put(TurnComplete())
        await asyncio.sleep(0.05)
        consent.granted = False  # the learner switched it off in Profile

    run(relay, [auth(), start()], [talk])
    processor.submit.assert_not_called()
    assessor.assess.assert_not_called()
    errors.record.assert_not_called()


# --- Focus words -------------------------------------------------------------------------------

LANG = "en"


def ids(count):
    return [uuid4() for _ in range(count)]


def make_chooser(*, due, notebooks, targets=None, video_titles=None, titles_fail=False):
    """``notebooks``: {name: [concept ids]}; each concept gets a saved row id of its own."""
    saved = {}
    rows = []
    for concept_ids in notebooks.values():
        for concept_id in concept_ids:
            saved.setdefault(concept_id, uuid4())
    for concept_id in {cid for group in notebooks.values() for cid in group} | set(due):
        rows.append({"id": str(saved.setdefault(concept_id, uuid4())), "concept_id": str(concept_id),
                     "status": (targets or {}).get(concept_id, "active")})
    groups = {name: uuid4() for name in notebooks}
    group_rows = [{"id": str(group_id), "name": name} for name, group_id in groups.items()]
    due_reader = Mock()
    due_reader.due_concept_ids.return_value = [str(concept_id) for concept_id in due]
    group_store, item_store, target_store = Mock(), Mock(), Mock()
    group_store.list_for_user.return_value = group_rows
    item_store.saved_ids.side_effect = lambda group_id: [saved[c] for c in notebooks[
        next(name for name, gid in groups.items() if gid == group_id)]]
    target_store.list_for_user.return_value = rows
    catalog = Mock()
    catalog.select.side_effect = lambda user_id, concept_ids, **kw: [
        LearnedItem(str(concept_id), f"w-{str(concept_id)[:4]}", "vocabulary", "nghĩa", "selected",
                    (f"w-{str(concept_id)[:4]}",)) for concept_id in concept_ids]
    titles = Mock()
    if titles_fail:
        titles.titles_for.side_effect = RuntimeError("database down")
    else:
        known_titles = {str(cid): title for cid, title in (video_titles or {}).items()}
        titles.titles_for.side_effect = lambda user_id, concept_ids: {
            cid: known_titles[cid] for cid in concept_ids if cid in known_titles}
    chooser = FocusWordChooser(due=due_reader, groups=group_store, group_items=item_store, targets=target_store,
                               catalog=catalog, video_topics=titles)
    return chooser, groups


def choose(chooser, topic_id=None):
    return chooser.choose(OWNER, language_code=LANG, support_language_code="vi", topic_id=topic_id)


def test_the_topic_with_the_most_due_words_is_chosen_and_only_its_due_words_are_practised():
    travel, food, other = ids(5), ids(2), ids(2)
    chooser, _ = make_chooser(due=[*food, *travel[:3], *other], notebooks={"Travel": travel, "Food": food})
    pick = choose(chooser)
    assert pick.title == "Travel"
    assert [item.concept_id for item in pick.items] == [str(cid) for cid in travel[:3]]


def test_at_most_twelve_focus_words_most_overdue_first():
    many = ids(20)
    chooser, _ = make_chooser(due=many, notebooks={"Big": many})
    assert [item.concept_id for item in choose(chooser).items] == [str(cid) for cid in many[:12]]


def test_the_learner_can_change_the_topic_but_only_to_one_of_their_own_notebooks():
    travel, food = ids(3), ids(2)
    chooser, groups = make_chooser(due=[*travel, *food], notebooks={"Travel": travel, "Food": food})
    pick = choose(chooser, groups["Food"])
    assert pick.title == "Food" and len(pick.items) == 2
    with pytest.raises(SpeakingPracticeError) as raised:
        choose(chooser, uuid4())
    assert raised.value.code == "companion_topic_not_found"


def test_a_topic_with_nothing_due_stays_in_the_selected_notebook():
    due, quiet = ids(3), ids(2)
    chooser, groups = make_chooser(due=due, notebooks={"Quiet": quiet})
    pick = choose(chooser, groups["Quiet"])
    assert pick.topic_id == groups["Quiet"] and pick.title == "Quiet" and pick.items == []


def test_without_notebooks_all_due_words_are_practised_together():
    due = ids(4)
    chooser, _ = make_chooser(due=due, notebooks={})
    assert len(choose(chooser).items) == 4


def test_nothing_due_means_no_focus_and_paused_words_are_left_out():
    due = ids(4)
    nothing, _ = make_chooser(due=[], notebooks={})
    assert choose(nothing) is None
    chooser, _ = make_chooser(due=due, notebooks={}, targets={due[0]: "suspended"})
    assert [item.concept_id for item in choose(chooser).items] == [str(due[1]), str(due[2]), str(due[3])]


# --- Words in no notebook are grouped by the video they came from ---------------------------------

def test_loose_due_words_form_a_topic_from_their_video_when_it_is_the_biggest():
    cars, loose_a = ids(2), ids(4)
    chooser, _ = make_chooser(due=[*cars, *loose_a], notebooks={"Cars": cars},
                              video_titles={cid: "Neil's job" for cid in loose_a})
    pick = choose(chooser)
    assert pick.title == "Words from “Neil's job”" and pick.topic_id is None
    assert [item.concept_id for item in pick.items] == [str(cid) for cid in loose_a]


def test_a_notebook_with_more_due_words_still_wins_and_notebook_words_are_not_grouped_twice():
    book, loose = ids(5), ids(2)
    chooser, _ = make_chooser(due=[*book, *loose], notebooks={"Travel": book},
                              video_titles={**{cid: "A video" for cid in book}, **{cid: "A video" for cid in loose}})
    pick = choose(chooser)
    assert pick.title == "Travel" and len(pick.items) == 5


def test_loose_words_without_a_known_video_or_when_the_lookup_fails_are_practised_together():
    due = ids(3)
    for kwargs in ({"video_titles": {}}, {"titles_fail": True}):
        chooser, _ = make_chooser(due=due, notebooks={}, **kwargs)
        pick = choose(chooser)
        assert pick.title == "Words you are reviewing today" and len(pick.items) == 3


# --- The conversation uses the focus ------------------------------------------------------------

def test_a_free_conversation_practises_the_chosen_focus_words_and_a_video_one_does_not():
    service = make_service()
    focus_items = [LearnedItem(str(uuid4()), "airport", "vocabulary", "sân bay", "selected", ("airport",))]
    service.focus = Mock()
    service.focus.choose.return_value = SimpleNamespace(title="Travel", topic_id=None, items=focus_items)
    service.target_catalog = Mock()
    service.target_catalog.select.return_value = focus_items
    prepared = service.prepare(USER, CompanionEntry.HOME, None)
    assert prepared.focused and prepared.ticket.topic == "Travel"
    assert [item.text for item in prepared.ticket.items] == ["airport"]
    video = service.prepare(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert not video.focused


def test_with_nothing_due_a_free_conversation_still_starts_from_the_videos():
    service = make_service()
    service.focus = Mock()
    service.focus.choose.return_value = None
    prepared = service.prepare(USER, CompanionEntry.HOME, None)
    assert not prepared.focused and prepared.ticket.items


# --- The adapter that finds the video a word came from -------------------------------------------

def test_the_newest_video_a_word_occurs_in_gives_its_topic_title():
    from app.bootstrap.wiring.speaking import _VideoTopics
    newest, older, word_a, word_b = uuid4(), uuid4(), uuid4(), uuid4()
    library, videos, objects = Mock(), Mock(), Mock()
    library.list_for_user.return_value = [SimpleNamespace(video_id=newest), SimpleNamespace(video_id=older)]
    videos.get_many_by_ids.return_value = {newest: SimpleNamespace(title="New talk"),
                                           older: SimpleNamespace(title="Old talk")}
    objects.list_for_videos_concepts.return_value = [
        SimpleNamespace(video_id=older, concept_id=word_a), SimpleNamespace(video_id=newest, concept_id=word_a),
        SimpleNamespace(video_id=older, concept_id=word_b)]
    found = _VideoTopics(library, videos, objects).titles_for(OWNER, [str(word_a), str(word_b)])
    assert found == {str(word_a): "New talk", str(word_b): "Old talk"}
    assert _VideoTopics(library, videos, objects).titles_for(OWNER, []) == {}
