"""FR-8.1: the agent teaches grammar when the learner says something wrong.

A light correction comes at once; a fuller explanation and "say it more naturally" only when the learner
asks. The kind of mistake is kept as a closed code (never the sentence) and only under the learner's
stored voice consent.
"""
import asyncio
from datetime import UTC, datetime
from uuid import uuid4


from app.modules.learner.application.agent_signals import AgentSignalsService
from app.modules.learner.contracts import ERROR_TYPE_CODES
from app.modules.learner.domain.agent_signals import AgentConsent, PersonalizationSignal, SignalKind
from app.modules.learning.domain.realtime import valid_error_type, valid_grammar_explanation
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, ToolCall, TranscriptPiece, TurnComplete, auth, service as relay_service, start,
)
from tests.learning.test_companion import OWNER

QUOTE = "Yesterday I go to the market."
CORRECTION = {"quote": "I go", "suggestion": "I went", "note": "Hôm qua nên dùng quá khứ nhé."}


class FakeErrorTypes:
    def __init__(self, recurring=(), fail=False):
        self.calls, self._recurring, self.fail = [], list(recurring), fail

    def record(self, user_id, *, language_code, signals):
        if self.fail:
            raise RuntimeError("database down")
        codes = tuple(code for kind, code in signals if kind == "error_type")
        if codes:
            self.calls.append((user_id, language_code, codes))

    def recurring(self, user_id, *, language_code):
        return list(self._recurring)


def run_session(script, *, errors=None, learner_text=QUOTE):
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.signals = errors if errors is not None else FakeErrorTypes()
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await voice.connection.events_queue.put(TranscriptPiece("learner", learner_text))
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
    return voice, channel, relay


def of_type(channel, kind):
    return [message for message in channel.json if message["type"] == kind]


# --- Pure pieces -------------------------------------------------------------------------------

def test_an_error_type_must_be_one_of_the_closed_codes():
    assert valid_error_type("verb_tense") == "verb_tense"
    for bad in ("Hà Nội", "my sister", "", None, 3, "verb_tense; drop table", "travel"):
        assert valid_error_type(bad) is None
    assert "verb_tense" in ERROR_TYPE_CODES


def test_an_explanation_is_short_and_an_example_is_in_the_learning_language():
    assert valid_grammar_explanation("Dùng quá khứ cho hôm qua.", "I went there.", "en") == (
        "Dùng quá khứ cho hôm qua.", "I went there.")
    assert valid_grammar_explanation("Dùng quá khứ.", None, "en") == ("Dùng quá khứ.", None)
    assert valid_grammar_explanation("", "I went.", "en") is None
    assert valid_grammar_explanation("x" * 601, None, "en") is None
    assert valid_grammar_explanation("Ok", "我去了。", "en") is None


# --- Light correction and the kind of mistake --------------------------------------------------

def test_a_correction_with_a_known_kind_is_kept_once_per_session_as_a_code_only():
    errors = FakeErrorTypes()
    _, channel, _ = run_session([
        ToolCall("1", "show_correction", {**CORRECTION, "error_type": "verb_tense"}),
        ToolCall("2", "show_correction", {**CORRECTION, "error_type": "verb_tense"}),
        ToolCall("3", "show_correction", {**CORRECTION, "error_type": "articles"}),
    ], errors=errors)
    assert errors.calls == [(OWNER, "en", ("verb_tense", "articles"))]
    assert len(of_type(channel, "correction")) == 3
    assert "I go" not in str(errors.calls) and "market" not in str(errors.calls)


def test_a_made_up_kind_is_ignored_but_the_correction_still_shows():
    errors = FakeErrorTypes()
    _, channel, _ = run_session([ToolCall("1", "show_correction", {**CORRECTION, "error_type": "Hà Nội"})], errors=errors)
    assert errors.calls == [] and len(of_type(channel, "correction")) == 1


def test_a_failing_signal_store_never_breaks_the_end_of_the_session():
    _, channel, _ = run_session([ToolCall("1", "show_correction", {**CORRECTION, "error_type": "verb_tense"})],
                                errors=FakeErrorTypes(fail=True))
    assert channel.json[-1]["type"] == "ended"


def test_the_summary_lists_the_kinds_of_mistake_as_codes_only():
    _, channel, _ = run_session([ToolCall("1", "show_correction", {**CORRECTION, "error_type": "verb_tense"})])
    summary = channel.json[-1]["summary"]
    assert summary["error_types"] == ["verb_tense"]
    assert "I go" not in str(channel.json[-1].get("summary")) and "Yesterday I go" not in str(channel.json[-1])


def test_without_a_correction_the_summary_has_no_error_types():
    _, channel, _ = run_session([])
    assert "error_types" not in channel.json[-1]["summary"]


# --- Fuller explanation, only on request -------------------------------------------------------

EXPLAIN = {"explanation": "Có từ 'yesterday' nên dùng quá khứ: go → went.", "example": "I went to the market."}


def test_an_explanation_is_shown_only_after_the_learner_asks_and_is_marked_unverified():
    voice, channel, _ = run_session(["explain", ToolCall("1", "explain_grammar", EXPLAIN)])
    assert "explain_grammar" in voice.connection.texts[0]
    [card] = of_type(channel, "grammar")
    assert card["explanation"] == EXPLAIN["explanation"] and card["example"] == EXPLAIN["example"]
    assert card["unverified"] is True
    assert voice.connection.tool_responses[0][2] == {"shown": True}


def test_an_explanation_the_agent_gives_unasked_is_shown():
    # PRD 8.12 point 1: the agent may explain without a button press; the content is still validated.
    voice, channel, _ = run_session([ToolCall("1", "explain_grammar", EXPLAIN)])
    assert len(of_type(channel, "grammar")) == 1 and voice.connection.texts == []
    assert voice.connection.tool_responses[0][2] == {"shown": True}


def test_a_bad_explanation_is_rejected():
    voice, channel, _ = run_session(["explain", ToolCall("1", "explain_grammar", {**EXPLAIN, "example": "我去了。"})])
    assert of_type(channel, "grammar") == []
    assert voice.connection.tool_responses[0][2] == {"shown": False}


# --- Say it more naturally ---------------------------------------------------------------------

NATURAL = {"options": [
    {"sentence": "I went to the market yesterday.", "explanation": "Cách nói thông thường nhất."},
    {"sentence": "I popped down to the market yesterday.", "explanation": "Thân mật hơn."},
    {"sentence": "I headed to the market yesterday.", "explanation": "Nghe tự nhiên khi kể chuyện."},
    {"sentence": "A fourth is dropped.", "explanation": "Thừa."},
]}


def test_more_natural_ways_are_shown_on_request_at_most_three_and_change_no_word_level():
    voice, channel, _ = run_session(["natural", ToolCall("1", "show_natural", NATURAL)])
    assert "show_natural" in voice.connection.texts[0]
    [card] = of_type(channel, "natural")
    assert [item["sentence"] for item in card["items"]] == [item["sentence"] for item in NATURAL["options"][:3]]


def test_natural_options_the_agent_offers_unasked_are_shown_at_most_three():
    voice, channel, _ = run_session([ToolCall("1", "show_natural", NATURAL)])
    [card] = of_type(channel, "natural")
    assert len(card["items"]) == 3 and voice.connection.tool_responses[0][2] == {"shown": True}


# --- The agent pays attention to the learner's own repeated mistakes ---------------------------

def test_the_instruction_names_the_learners_recurring_kinds_of_mistake():
    voice, _, _ = run_session([], errors=FakeErrorTypes(recurring=["verb_tense", "articles"]))
    instruction = voice.opened[0][1]
    assert "verb_tense" in instruction and "articles" in instruction


def test_without_recurring_mistakes_the_instruction_says_nothing_about_them():
    voice, _, _ = run_session([], errors=FakeErrorTypes())
    assert "often makes" not in voice.opened[0][1]


# --- The adapter between the conversation and the stored signals -------------------------------

class _Consents:
    def __init__(self, granted):
        self.row = AgentConsent(user_id=OWNER, voice_consent=granted, decided_at=datetime.now(UTC))

    def get(self, user_id):
        return self.row if user_id == OWNER else None


class _Signals:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def list_all(self, user_id):
        return [row for row in self.rows if row.user_id == user_id]

    def record(self, user_id, *, language_code, kind, code, replace_kind):
        self.rows.append(PersonalizationSignal(id=uuid4(), user_id=user_id, language_code=language_code, kind=kind,
                                               code=code))


def adapter(granted=True, rows=()):
    from app.bootstrap.wiring.agent import PersonalizationSignals
    return PersonalizationSignals(AgentSignalsService(consents=_Consents(granted), signals=_Signals(rows)))


def test_kinds_are_stored_as_error_type_signals_only_under_granted_consent():
    granted, revoked = adapter(True), adapter(False)
    granted.record(OWNER, language_code="en", signals=[("error_type", "verb_tense"), ("error_type", "Hà Nội")])
    revoked.record(OWNER, language_code="en", signals=[("error_type", "verb_tense")])
    assert [(row.kind, row.code) for row in granted.signals.store.rows] == [(SignalKind.ERROR_TYPE, "verb_tense")]
    assert revoked.signals.store.rows == []


def test_only_kinds_seen_before_in_this_language_count_as_recurring():
    def row(code, count, language="en", kind=SignalKind.ERROR_TYPE):
        return PersonalizationSignal(id=uuid4(), user_id=OWNER, language_code=language, kind=kind, code=code,
                                     usage_count=count)
    rows = [row("verb_tense", 3), row("articles", 1), row("word_order", 2, language="zh"), row("travel", 5, kind=SignalKind.TOPIC),
            row("prepositions", 2)]
    assert adapter(True, rows).recurring(OWNER, language_code="en") == ["verb_tense", "prepositions"]
    assert adapter(False, rows).recurring(OWNER, language_code="en") == []
