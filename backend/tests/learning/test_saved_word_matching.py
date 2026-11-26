"""FR-3.5: every conversation is checked against ALL of the learner's saved words.

A cheap form match picks the few saved words the learner actually said; only those reach the
model, which still checks the meaning. No live AI: the analysis service is a mock.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4


from app.modules.learning.application.learned_items import LearnedItem
from app.modules.learning.application.session_events import LearnerTurn
from app.modules.learning.application.spoken_words import saved_word_targets, turns_with_server_support
from tests.learning.test_companion import OWNER
from tests.learning.test_realtime_companion import (
    FakeChannel, TranscriptPiece, TurnComplete, auth, service as relay_service, start,
)

BANK, TRAVEL, PAINT, PLAIN = uuid4(), uuid4(), uuid4(), uuid4()


def item(concept_id, text, meaning="a meaning", forms=None):
    return LearnedItem(str(concept_id), text, "vocabulary", meaning, "selected", tuple(forms or [text]))


def turns(*texts):
    return [LearnerTurn(text=text) for text in texts]


SAVED = [item(BANK, "bank"), item(TRAVEL, "travel", forms=["travel", "travelling"]),
         item(PAINT, "paint", meaning=None), item(PLAIN, "plain")]


def ids(items):
    return [entry.concept_id for entry in items]


def test_only_saved_words_the_learner_said_as_whole_words_are_candidates():
    found = saved_word_targets(SAVED, turns("I went to the banker.", "I love travelling a lot."), "en")
    assert ids(found) == [str(TRAVEL)]


def test_candidates_follow_the_order_they_were_first_said_and_skip_words_without_a_meaning():
    found = saved_word_targets(SAVED, turns("I paint and travel.", "Then I go to the bank."), "en")
    assert ids(found) == [str(TRAVEL), str(BANK)]


def test_chinese_words_match_inside_unspaced_text():
    zh = [item(BANK, "银行"), item(TRAVEL, "旅行")]
    assert ids(saved_word_targets(zh, turns("我喜欢旅行，也常去银行。"), "zh")) == [str(BANK), str(TRAVEL)] \
        or ids(saved_word_targets(zh, turns("我喜欢旅行，也常去银行。"), "zh")) == [str(TRAVEL), str(BANK)]


def test_said_words_come_before_an_unsaid_selected_word_and_the_total_is_capped_at_twelve():
    # Was "selected words are kept first": an unsaid selected word took a slot from a said one
    # (Codex review, 2026-11-05). Said words now come first; an unsaid selected word only fills a free slot.
    many = [item(uuid4(), f"word{index}") for index in range(20)]
    said = turns(" ".join(entry.text for entry in many))
    selected = [item(BANK, "bank")]
    found = saved_word_targets(many, said, "en", selected=selected)
    assert str(BANK) not in ids(found) and len(found) == 12
    assert ids(saved_word_targets(many[:3], turns("word0"), "en", selected=selected)) == [many[0].concept_id, str(BANK)]
    assert ids(saved_word_targets(many, said, "en"))[:2] == [many[0].concept_id, many[1].concept_id]


def test_a_said_saved_word_is_checked_even_when_twelve_words_were_selected():
    # Codex review (2026-11-05): twelve selected words used to fill every slot, so a saved word the
    # learner really said was never checked. Words that were said come first.
    selected = [item(uuid4(), f"focus{index}") for index in range(12)]
    found = saved_word_targets(SAVED, turns("I went to the bank."), "en", selected=selected)
    assert ids(found)[0] == str(BANK) and len(found) == 12


def test_thirteen_said_saved_words_keep_the_first_twelve_said():
    many = [item(uuid4(), f"word{index}") for index in range(13)]
    selected = [item(BANK, "bank")]
    found = saved_word_targets(many, turns(" ".join(entry.text for entry in many)), "en", selected=selected)
    assert ids(found) == [entry.concept_id for entry in many[:12]]


def test_a_said_selected_word_comes_before_a_later_said_saved_word():
    selected = [item(TRAVEL, "travel")]
    found = saved_word_targets(SAVED, turns("I travel.", "Then I go to the bank."), "en", selected=selected)
    assert ids(found) == [str(TRAVEL), str(BANK)]


def test_a_word_the_companion_already_said_before_the_turn_is_assisted_for_that_turn_only():
    word = item(TRAVEL, "travel")
    said = [LearnerTurn(text="I travel a lot.", examples_seen=0), LearnerTurn(text="I travel by train.", examples_seen=1)]
    out = turns_with_server_support(said, ["Do you like to travel?"], [word], "en")
    assert [turn.assisted_ids for turn in out] == [[], [TRAVEL]]


def test_server_support_keeps_what_the_relay_already_recorded():
    word = item(TRAVEL, "travel")
    said = [LearnerTurn(text="I travel.", assisted_ids=[BANK], examples_seen=0)]
    assert turns_with_server_support(said, [], [word], "en")[0].assisted_ids == [BANK]


# --- Relay ----------------------------------------------------------------------------------

class _Denied:
    def has_consent(self, user_id):
        return False


def run_session(*, consented=True, selected=None, saved=SAVED, said=("I travel and I like the bank.",),
                companion_first=None, catalog_error=False):
    async def scenario():
        relay = relay_service()
        processor = Mock()
        processor.submit.return_value = {"session_id": str(uuid4()), "status": "queued"}
        relay.session_events = processor
        relay.setup.target_catalog = Mock()
        relay.setup.target_catalog.select.return_value = selected or []
        if catalog_error:
            relay.setup.target_catalog.saved_items.side_effect = RuntimeError("database down")
        else:
            relay.setup.target_catalog.saved_items.return_value = saved
        if not consented:
            relay.consent = _Denied()
        if selected:
            relay.setup.focus = Mock()
            relay.setup.focus.choose.return_value = SimpleNamespace(title="Topic", topic_id=None, items=selected)
            channel = FakeChannel([auth(), ("text", '{"type":"start","entry":"home"}')])
        else:
            channel = FakeChannel([auth(), start()])
        task = asyncio.create_task(relay.run(channel))
        try:
            for _ in range(100):
                if relay.voice.opened:
                    break
                await asyncio.sleep(.01)
            events = []
            if companion_first:
                events.append(TranscriptPiece("companion", companion_first))
            for text in said:
                events += [TranscriptPiece("learner", text), TurnComplete()]
            for event in events:
                await relay.voice.connection.events_queue.put(event)
            for _ in range(100):
                if channel.types().count("turn_complete") >= len(said):
                    break
                await asyncio.sleep(.01)
            await channel.inbound.put(("text", '{"type":"end"}'))
            await asyncio.wait_for(task, 2)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return relay, processor, channel
    return asyncio.run(scenario())


def test_a_free_conversation_sends_only_the_matched_saved_words_to_analysis():
    relay, processor, channel = run_session()
    data = processor.submit.call_args.args[0]
    assert [target.concept_id for target in data.targets] == [BANK, TRAVEL]
    assert [target.text for target in data.targets] == ["bank", "travel"]
    assert channel.json[-1]["analysis"]["status"] == "queued"
    relay.setup.target_catalog.saved_items.assert_called_once()


def test_without_consent_there_is_no_session_so_nothing_is_read_or_queued():
    relay, processor, channel = run_session(consented=False)
    processor.submit.assert_not_called()
    relay.setup.target_catalog.saved_items.assert_not_called()
    assert channel.json[-1]["code"] == "voice_consent_required"


def test_no_saved_word_said_means_no_analysis_and_no_model_call():
    _, processor, channel = run_session(said=("The weather is nice today.",))
    processor.submit.assert_not_called()
    assert "analysis" not in channel.json[-1]


def test_a_word_the_companion_said_first_is_credited_as_assisted():
    _, processor, _ = run_session(said=("I travel often.",), companion_first="Do you like to travel?")
    data = processor.submit.call_args.args[0]
    assert data.turns[0].assisted_ids == [TRAVEL]


def test_a_free_conversation_still_ends_with_follow_ups():
    _, _, channel = run_session()
    assert channel.json[-1]["type"] == "ended" and "follow_ups" in channel.json[-1]


def test_a_failing_word_lookup_never_breaks_the_end_of_the_session():
    _, processor, channel = run_session(catalog_error=True)
    processor.submit.assert_not_called()
    assert channel.json[-1]["type"] == "ended"
    assert channel.json[-1]["analysis"]["status"] == "unavailable"


def test_selected_words_stay_first_and_other_saved_words_are_added():
    selected = [item(PLAIN, "plain")]
    _, processor, _ = run_session(selected=selected, said=("I travel and it was plain.",))
    data = processor.submit.call_args.args[0]
    assert [target.concept_id for target in data.targets] == [PLAIN, TRAVEL]


def test_a_selected_word_session_is_still_analysed_when_the_saved_word_lookup_fails():
    selected = [item(PLAIN, "plain")]
    _, processor, _ = run_session(selected=selected, said=("It was plain.",), catalog_error=True)
    assert [target.concept_id for target in processor.submit.call_args.args[0].targets] == [PLAIN]


def test_a_paused_saved_word_still_counts():
    from tests.learning.test_l2_speaking import FIRST, SECOND, catalog
    items = catalog(statuses=("active", "suspended")).saved_items(
        OWNER, language_code="en", support_language_code="vi")
    assert sorted(item.concept_id for item in items) == sorted([str(FIRST), str(SECOND)])
