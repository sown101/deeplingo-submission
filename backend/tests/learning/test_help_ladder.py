"""FR-3.2 / FR-3.9 / FR-3.10 under PRD 8.12: Help and Ideas as explicit requests, help the agent gives unasked,
hesitation reported to the agent, end-of-session summary.

The agent chooses how much a hint gives (PRD 8.12 points 1 and 5); the server still validates every field.
No live AI: the provider connection is a fake.
"""
import asyncio

import pytest

from app.modules.learning.application.agent.prompts import hesitation_event
from app.modules.learning.domain.realtime import asks_to_explain, says_stuck, valid_suggestions
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, ToolCall, TranscriptPiece, TurnComplete, auth, service, start,
)

FULL = {"words": ["fly", "airport"], "question": "Bạn thích gì?", "frame": "I like ___.",
        "frame_reason": "Dùng like.", "model_sentence": "I like flying."}


def test_suggestions_are_at_most_three_short_sentences_with_an_explanation():
    ok = [{"sentence": "I like flying.", "explanation": "Nói sở thích."}]
    assert valid_suggestions(ok, "en") == ok
    many = [{"sentence": f"I like {n}.", "explanation": "x"} for n in range(5)]
    assert len(valid_suggestions(many, "en")) == 3
    assert valid_suggestions([{"sentence": "", "explanation": "x"}], "en") == []
    assert valid_suggestions([{"sentence": "I like it.", "explanation": ""}], "en") == []
    assert valid_suggestions([{"sentence": "x" * 301, "explanation": "x"}], "en") == []
    assert valid_suggestions([{"sentence": "你好", "explanation": "x"}], "en") == []
    assert valid_suggestions("not a list", "en") == []


def run_session(script):
    """``script``: ("help"|"suggest"|"end"|event, ...) in order; returns (voice, channel, relay)."""
    voice = FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for step in script:
            if step in ("help", "suggest"):
                await channel.inbound.put(("text", '{"type": "%s"}' % step))
            else:
                await voice.connection.events_queue.put(step)
            await asyncio.sleep(0.03)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())
    return voice, channel, relay


def hints(channel):
    return [message for message in channel.json if message["type"] == "hint"]


def test_a_hint_tap_asks_the_agent_and_the_card_shows_what_the_agent_chose():
    voice, channel, _ = run_session(["help", ToolCall("1", "show_hint", FULL)])
    assert len(voice.connection.texts) == 1 and "pressed Hint" in voice.connection.texts[0]
    [hint] = hints(channel)
    assert hint["level"] == 3 and hint["auto"] is False and hint["question"] == "Bạn thích gì?"
    assert [item["text"] for item in hint["items"]] == ["fly", "airport"]
    assert hint["frame"] == "I like ___." and hint["model_sentence"] == "I like flying."


def test_the_hint_request_tells_the_agent_what_the_learner_has_already_seen():
    question_only = {"words": ["fly"], "question": "Bạn thích gì?"}
    with_frame = {**question_only, "frame": "I like ___.", "frame_reason": "Dùng like."}
    voice, channel, _ = run_session(["help", ToolCall("1", "show_hint", question_only), "help",
                                     ToolCall("2", "show_hint", with_frame), "help"])
    first, second, third = voice.connection.texts
    assert "so far" not in first
    assert "so far: a guiding question and words" in second
    assert "so far: a question, words and a sentence frame" in third
    assert [hint["level"] for hint in hints(channel)] == [1, 2]


def test_a_new_question_starts_the_help_again():
    voice, _, _ = run_session(["help", ToolCall("1", "show_hint", FULL), TranscriptPiece("learner", "I like to fly."),
                               TurnComplete(), "help"])
    first, after_answer = voice.connection.texts
    assert "so far" not in first
    assert "so far" not in after_answer  # the learner answered: the full hint is not carried to the next question
    voice, _, _ = run_session(["help", ToolCall("1", "show_hint", FULL), "help"])
    assert "so far: everything" in voice.connection.texts[-1]  # without an answer it is


def test_a_hint_the_agent_offers_unasked_is_shown_as_the_agent_chose_it():
    _, channel, _ = run_session([ToolCall("1", "show_hint", FULL)])
    [hint] = hints(channel)
    assert hint["level"] == 3 and hint["frame"] == "I like ___." and hint["model_sentence"] == "I like flying."


def test_a_hint_without_a_question_at_the_first_step_is_not_shown():
    voice, channel, _ = run_session(["help", ToolCall("1", "show_hint", {"words": ["fly"], "frame": "I like ___.",
                                                                          "frame_reason": "x"})])
    assert hints(channel) == []
    assert voice.connection.tool_responses[0][2] == {"shown": False, "reason": "question is required"}


SUGGESTIONS = {"suggestions": [
    {"sentence": "I like flying.", "explanation": "Nói bạn thích đi máy bay."},
    {"sentence": "I want to visit Japan.", "explanation": "Nói nơi bạn muốn đến."},
    {"sentence": "I am afraid of heights.", "explanation": "Nói bạn sợ độ cao."},
    {"sentence": "A fourth one is dropped.", "explanation": "Thừa."},
]}


def test_a_suggest_tap_asks_the_model_and_shows_at_most_three_sentences():
    voice, channel, _ = run_session(["suggest", ToolCall("1", "show_suggestions", SUGGESTIONS)])
    assert len(voice.connection.texts) == 1 and "show_suggestions" in voice.connection.texts[0]
    [card] = [message for message in channel.json if message["type"] == "suggestions"]
    assert [item["sentence"] for item in card["items"]] == [
        "I like flying.", "I want to visit Japan.", "I am afraid of heights."]
    assert voice.connection.tool_responses[0][2] == {"shown": True}


def test_suggestions_the_agent_offers_unasked_are_shown():
    voice, channel, _ = run_session([ToolCall("1", "show_suggestions", SUGGESTIONS)])
    [card] = [message for message in channel.json if message["type"] == "suggestions"]
    assert len(card["items"]) == 3 and voice.connection.tool_responses[0][2] == {"shown": True}


def test_a_spoken_wrong_language_suggestion_is_rejected():
    bad = {"suggestions": [{"sentence": "我喜欢飞。", "explanation": "x"}]}
    voice, channel, _ = run_session(["suggest", ToolCall("1", "show_suggestions", bad)])
    assert not [message for message in channel.json if message["type"] == "suggestions"]
    assert voice.connection.tool_responses[0][2] == {"shown": False}


def test_the_end_of_a_session_carries_a_plain_summary_without_content_or_scores():
    _, channel, _ = run_session([
        TranscriptPiece("learner", "I go to the market."), TurnComplete(),
        ToolCall("1", "show_correction", {"quote": "I go", "suggestion": "I went", "note": "Thử nhé."}),
        "help", ToolCall("2", "show_hint", FULL),
        "suggest", ToolCall("3", "show_suggestions", SUGGESTIONS),
    ])
    summary = channel.json[-1]["summary"]
    assert summary == {"spoken_turns": 1, "corrections": 1, "hints": 1, "suggestions": 1,
                       "words_to_reuse": ["fly", "airport"]}
    assert "market" not in str(channel.json[-1])
    assert not {"score", "level", "grade"} & set(summary)


def test_a_session_where_the_learner_never_spoke_has_no_summary():
    _, channel, _ = run_session([])
    assert "summary" not in channel.json[-1]


@pytest.mark.parametrize("text, language, stuck", [
    ("I don't know what to say.", "en", True), ("I don\u2019t know", "en", True), ("Um, no idea.", "en", True),
    ("I'm stuck", "en", True), ("I know the answer.", "en", False), ("Nobody knows the idea", "en", False),
    ("我不知道说什么", "zh", True), ("我不会说", "zh", True), ("我知道", "zh", False),
    # Vietnamese, the support language, in either learning language.
    ("Tôi không biết", "en", True), ("Ừm... quên rồi", "zh", True), ("Chịu khó học nhé", "en", False),
])
def test_the_learner_can_say_plainly_that_they_do_not_know(text, language, stuck):
    assert says_stuck(text, language) is stuck


def test_a_learner_who_says_they_do_not_know_is_reported_to_the_agent_which_chooses_the_hint():
    # PRD 8.12 point 5: "I can't say it" and fillers are stalls; the server reports them, the agent chooses.
    voice, channel, _ = run_session([
        TranscriptPiece("learner", "I don't know what to say."), TurnComplete(),
        ToolCall("1", "show_hint", {"words": ["fly"], "question": "Bạn thích gì?"}),
        TranscriptPiece("learner", "Um... uh."), TurnComplete(), ToolCall("2", "show_hint", FULL)])
    first, second = hints(channel)
    assert (first["level"], first["auto"], first["frame"]) == (1, True, None)
    assert (second["level"], second["auto"]) == (3, True) and second["model_sentence"] == "I like flying."
    assert [text for text in voice.connection.texts if text.startswith("(Event:")] == [
        hesitation_event("stuck", 1), hesitation_event("fillers", 2)]


def test_a_hint_after_an_ordinary_answer_is_the_agents_choice_and_not_marked_as_a_stall():
    voice, channel, _ = run_session([TranscriptPiece("learner", "I like flying."), ToolCall("1", "show_hint", FULL)])
    [hint] = hints(channel)
    assert hint["level"] == 3 and hint["auto"] is False
    assert not [text for text in voice.connection.texts if text.startswith("(Event:")]


@pytest.mark.parametrize("text, language, asks", [
    ("Why do we say went?", "en", True), ("Can you explain that?", "en", True), ("what's the rule here", "en", True),
    ("Please explain why.", "en", True), ("Why is it plural", "en", True),
    ("I want to explain my job.", "en", False), ("I don't know why I like it.", "en", False),
    ("The explanation was long.", "en", False), ("I went to the market.", "en", False),
    ("为什么用了？", "zh", True), ("请解释一下", "zh", True), ("我喜欢解释。", "zh", False),
    ("giải thích giúp tôi", "en", True), ("tại sao lại dùng went", "en", True),
])
def test_the_learner_can_ask_why_in_words(text, language, asks):
    assert asks_to_explain(text, language) is asks


def say_and_collect(learner_pieces, tools=()):
    voice = FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for piece in learner_pieces:
            await voice.connection.events_queue.put(TranscriptPiece("learner", piece))
            await asyncio.sleep(0.02)
        for index, (name, args) in enumerate(tools):
            await voice.connection.events_queue.put(ToolCall(str(index), name, args))
            await asyncio.sleep(0.03)
        await voice.connection.events_queue.put(TurnComplete())
        await asyncio.sleep(0.03)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())
    return voice, channel


def test_asking_why_aloud_asks_the_agent_for_the_rule_once_and_the_card_is_allowed():
    voice, channel = say_and_collect(["Why do ", "we say ", "went? And why ", "is it past?"], tools=[
        ("explain_grammar", {"explanation": "Có yesterday nên dùng quá khứ.", "example": "I went there."})])
    cues = [text for text in voice.connection.texts if "explain_grammar" in text]
    assert len(cues) == 1
    assert [message for message in channel.json if message["type"] == "grammar"]


def test_an_ordinary_sentence_sends_no_request_but_the_agent_may_still_explain():
    voice, channel = say_and_collect(["I want to explain my job. ", "I work on a farm."], tools=[
        ("explain_grammar", {"explanation": "Quy tắc.", "example": None})])
    assert not [text for text in voice.connection.texts if "explain_grammar" in text]
    assert [message for message in channel.json if message["type"] == "grammar"]
