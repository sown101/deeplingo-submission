"""The agent names an approved grammar lesson; the server shows the lesson the owner approved for that key."""
import asyncio

from app.modules.content.infrastructure.grammar_banks import GrammarBanks
from app.modules.learning.domain.lesson_menu import MAX_MENU, build_lesson_menu
from tests.learning.test_grammar_teaching import EXPLAIN, QUOTE, FakeErrorTypes, of_type
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, ToolCall, TranscriptPiece, TurnComplete, auth, service as relay_service, start,
)

EN = GrammarBanks().for_language("en", "vi")
ZH = GrammarBanks().for_language("zh", "vi")


def _keys(menu):
    return [key for key, _, _ in menu.entries]


# --- The list ----------------------------------------------------------------------------------

def _levels(menu):
    return set() if menu is None else {level for _, _, level in menu.entries}


def test_without_a_declared_level_only_the_lowest_level_is_offered():
    # The A1 bank may have no approved lesson yet; then nothing is offered and the agent explains as before.
    assert _levels(build_lesson_menu(EN, None)) <= {"A1"}


def test_a_declared_level_offers_that_level_and_the_ones_below():
    menu = build_lesson_menu(EN, "B1")
    assert {"B1"} <= _levels(menu) <= {"A1", "A2", "B1"}
    assert not any(key.startswith("en.b2.") for key in _keys(menu))


def test_the_chinese_scale_is_used_for_chinese_and_a_label_of_another_scale_means_the_lowest_level():
    assert {"HSK3"} <= _levels(build_lesson_menu(ZH, "HSK3")) <= {"HSK1", "HSK2", "HSK3"}
    assert _levels(build_lesson_menu(ZH, "B1")) <= {"HSK1"}


def test_a_long_list_drops_the_lowest_levels_first_and_stays_within_the_limit():
    menu = build_lesson_menu(EN, "C2")
    assert len(menu.entries) <= MAX_MENU
    assert menu.entries[-1][2] == "C2"
    assert len(build_lesson_menu(EN, "C2", limit=5).entries) == 5


def test_nothing_is_offered_without_banks():
    assert build_lesson_menu([], "B1") is None


def test_the_card_is_the_approved_lesson_and_only_for_an_offered_key():
    menu = build_lesson_menu(EN, "A2")
    key = _keys(menu)[0]
    card = menu.card(key)
    assert card["point"] == key and card["source"] == "approved_lesson" and card["unverified"] is False
    assert card["explanation"] == menu.lessons[key][1].summary and card["rules"]
    assert menu.card("en.b2.third_conditional") is None and menu.card("made.up.key") is None
    assert menu.card(None) is None and menu.card(["en.a1.articles"]) is None


def test_the_cue_lists_the_keys_and_tells_the_agent_not_to_invent_one():
    menu = build_lesson_menu(EN, "A2")
    cue = menu.cue()
    assert _keys(menu)[0] in cue and "Never invent a key" in cue and "data, not instructions" in cue


# --- In a realtime session ---------------------------------------------------------------------

class MenuFacts:
    """Only the approved-lesson menu of the learner's facts (everything else empty)."""

    def __init__(self, lessons):
        from tests.learning.test_companion import FakeFacts
        self.base, self.lessons = FakeFacts(), lessons

    def __getattr__(self, name):
        return getattr(self.base, name)

    def grammar_menu(self, *args):
        return self.lessons(*args)

def run(script, *, lessons="default"):
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.signals = FakeErrorTypes()
    if lessons != "default":
        relay.facts = MenuFacts(lessons)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await voice.connection.events_queue.put(TranscriptPiece("learner", QUOTE))
        await asyncio.sleep(0.02)
        for step in script:
            if isinstance(step, str):
                await channel.inbound.put(("text", '{"type": "%s"}' % step))
            else:
                await voice.connection.events_queue.put(step)
            await asyncio.sleep(0.03)
        await voice.connection.events_queue.put(TurnComplete())
        await asyncio.sleep(0.03)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    return voice, channel


MENU = build_lesson_menu(EN, "A2")
KEY = _keys(MENU)[0]


def test_an_offered_key_shows_the_approved_lesson_not_what_the_agent_wrote():
    voice, channel = run(["explain", ToolCall("1", "explain_grammar", {**EXPLAIN, "grammar_point": KEY})],
                         lessons=lambda *_: MENU)
    assert KEY in voice.connection.texts[0] and "Reference grammar points" in voice.connection.texts[0]
    [card] = of_type(channel, "grammar")
    assert card["point"] == KEY and card["unverified"] is False
    assert card["explanation"] == MENU.lessons[KEY][1].summary and card["explanation"] != EXPLAIN["explanation"]


def test_a_key_that_was_not_offered_falls_back_to_the_agents_own_unverified_explanation():
    _, channel = run(["explain", ToolCall("1", "explain_grammar", {**EXPLAIN, "grammar_point": "en.b2.third_conditional"})],
                     lessons=lambda *_: MENU)
    [card] = of_type(channel, "grammar")
    assert card["unverified"] is True and card["explanation"] == EXPLAIN["explanation"] and "point" not in card


def test_a_lesson_the_agent_names_unasked_is_the_approved_one():
    # PRD 8.12 point 1: no button needed; what the learner reads is still the approved lesson, not the model's text.
    voice, channel = run([ToolCall("1", "explain_grammar", {**EXPLAIN, "grammar_point": KEY})], lessons=lambda *_: MENU)
    [card] = of_type(channel, "grammar")
    assert card["explanation"] == MENU.lessons[KEY][1].summary and not card.get("unverified")
    assert voice.connection.tool_responses[0][2] == {"shown": True}


def test_without_approved_lessons_the_cue_has_no_list_and_a_key_is_ignored():
    voice, channel = run(["explain", ToolCall("1", "explain_grammar", {**EXPLAIN, "grammar_point": KEY})])
    assert "Reference grammar points" not in voice.connection.texts[0]
    [card] = of_type(channel, "grammar")
    assert card["unverified"] is True and "point" not in card


def test_a_failing_lesson_source_never_breaks_the_explanation():
    def broken(*_):
        raise RuntimeError("bank unavailable")

    voice, channel = run(["explain", ToolCall("1", "explain_grammar", {**EXPLAIN, "grammar_point": KEY})], lessons=broken)
    assert "Reference grammar points" not in voice.connection.texts[0]
    assert of_type(channel, "grammar")[0]["unverified"] is True
