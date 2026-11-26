"""FR-8.1: at the end of a session the agent gives a short note for each kind of grammar mistake that came
up, from fixed text (no model call), in the support language."""
import asyncio


from app.modules.learner.contracts import ERROR_TYPE_CODES
from app.modules.learning.domain.grammar_notes import grammar_notes
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, ToolCall, TranscriptPiece, TurnComplete, auth, service as relay_service, start,
)

CJK = range(0x4E00, 0xA000)


def test_every_kind_of_mistake_has_a_note_in_both_support_languages():
    for support in ("vi", "en"):
        notes = {code: grammar_notes([code], "en", support) for code in sorted(ERROR_TYPE_CODES)}
        assert all(len(found) == 1 for found in notes.values()), support
        notes = {code: found[0] for code, found in notes.items()}
        assert all(0 < len(note["note"]) <= 300 for note in notes.values())


def test_the_note_follows_the_support_language_and_falls_back_to_english():
    [vi] = grammar_notes(["articles"], "en", "vi")
    [en] = grammar_notes(["articles"], "en", "en")
    [other] = grammar_notes(["articles"], "en", "fr")
    assert vi["note"] != en["note"] and other["note"] == en["note"]


def test_an_example_is_in_the_learning_language_or_absent():
    for code in sorted(ERROR_TYPE_CODES):
        for language in ("en", "zh"):
            [note] = grammar_notes([code], language, "vi")
            example = note["example"]
            if example is not None:
                assert any(ord(ch) in CJK for ch in example) == (language == "zh"), (code, language)


def test_only_the_kinds_asked_for_and_at_most_three_unique_ones():
    found = grammar_notes(["articles", "articles", "verb_tense", "word_order", "pronouns", "conjunctions"], "en", "vi")
    assert [note["code"] for note in found] == ["articles", "verb_tense", "word_order"]
    assert grammar_notes(["Hà Nội", "x"], "en", "vi") == []


def run_session(tools):
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await voice.connection.events_queue.put(TranscriptPiece("learner", "Yesterday I go to the market."))
        await voice.connection.events_queue.put(TurnComplete())
        await asyncio.sleep(0.04)
        for index, args in enumerate(tools):
            await voice.connection.events_queue.put(ToolCall(str(index), "show_correction", args))
            await asyncio.sleep(0.03)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 3)

    asyncio.run(scenario())
    return channel


FIX = {"quote": "I go", "suggestion": "I went", "note": "Hôm qua nên dùng quá khứ."}


def test_the_summary_carries_a_note_for_each_kind_of_mistake_without_the_sentence():
    channel = run_session([{**FIX, "error_type": "verb_tense"}])
    summary = channel.json[-1]["summary"]
    [note] = summary["grammar_notes"]
    assert note["code"] == "verb_tense" and note["note"] and "Yesterday I go" not in str(summary)
    assert summary["error_types"] == ["verb_tense"]


def test_no_mistake_kind_means_no_grammar_notes():
    channel = run_session([FIX])
    assert "grammar_notes" not in channel.json[-1]["summary"]
