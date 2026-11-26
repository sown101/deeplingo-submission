"""Live voice: a function call with arguments of the wrong type is refused, never fatal.

Codex review (2026-11-05): show_hint({"words": 123}) raised TypeError, no tool response reached the
model and the conversation stalled. Every call must get a response. No live AI: the voice is a fake.
"""
import pytest

from tests.learning.test_grammar_teaching import of_type, run_session
from tests.learning.test_realtime_companion import ToolCall

BAD_CALLS = [
    ("show_hint", {"words": 123, "question": "What did you buy?"}),
    ("show_hint", {"words": "market", "question": 5, "frame": ["I"], "model_sentence": {"a": 1}}),
    ("show_suggestions", {"suggestions": "say something"}),
    ("explain_grammar", {"explanation": 1, "example": ["Yesterday I went."]}),
    ("show_natural", {"options": 7}),
    ("note_interest", {"topic": ["travel"]}),
    ("note_goal", {"goal": 42}),
    ("show_correction", {"quote": 1, "suggestion": None, "note": [], "error_type": {"x": 1}}),
    ("lookup_word", {"word": {"text": "market"}}),
]


@pytest.mark.parametrize(("name", "args"), BAD_CALLS, ids=[f"{name}-{index}" for index, (name, _) in enumerate(BAD_CALLS)])
def test_a_call_with_wrong_argument_types_gets_a_response_and_the_session_goes_on(name, args):
    voice, channel, _ = run_session([ToolCall("bad", name, args), ToolCall("good", "show_hint", {
        "words": [], "question": "What did you buy at the market?"})])
    responses = {call_id: response for call_id, _, response in voice.connection.tool_responses}
    # Every call is answered; wrongly typed values are dropped (a valid hint question may still show, without words).
    assert "bad" in responses and responses["bad"].get("words_shown", []) == []
    # The next, valid call is still handled: the conversation did not stall.
    assert responses["good"]["shown"] is True
    assert of_type(channel, "hint")


def test_an_argument_error_inside_any_tool_is_answered_with_an_error(monkeypatch):
    # The safety net for checks a tool does not make itself yet: the model still gets a response.
    from app.modules.learning.application.agent import tools as realtime

    def broken(*_args, **_kwargs):
        raise TypeError("synthetic bad argument")

    monkeypatch.setattr(realtime, "valid_suggestions", broken)
    voice, _, _ = run_session(["suggest", ToolCall("bad", "show_suggestions", {"suggestions": []})])
    responses = {call_id: response for call_id, _, response in voice.connection.tool_responses}
    assert responses["bad"]["error"] == "invalid arguments"  # plus the core's guidance for the blank argument
