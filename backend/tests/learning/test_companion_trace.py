"""The companion trace records timings, counts and outcome codes, never content."""
import logging

from app.modules.learning.application.agent.trace import CompanionTrace
from app.modules.learning.domain.companion import CompanionEntry
from app.modules.learning.domain.speech_audio import SpeechAudio
from tests.learning.speaking_fixtures import pcm_silence
from tests.learning.test_companion import (
    AIRPORT,
    FLY,
    ITEM_ID,
    OWNER,
    USER,
    error_of,
    make_service,
    speech,
    started,
    turn_output,
)

TRACE_LOGGER = "app.modules.learning.application.agent.trace"
LEARNER_WORDS = "I like fly to the secretcode airport"
CORRECTION = {"quote": "I like fly", "suggestion": "I like flying", "note_support": "Thử nói lại với flying nhé."}


def trace_lines(caplog):
    return [record.getMessage() for record in caplog.records if record.name == TRACE_LOGGER]


def fields(line):
    return dict(part.split("=", 1) for part in line.removeprefix("companion_trace ").split())


def test_start_and_turn_each_emit_one_trace_with_phase_timings(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    service = make_service(outputs=(turn_output(), turn_output(correction=CORRECTION, next="retry",
                                                              used_item_ids=[AIRPORT.concept_id])),
                           texts=[LEARNER_WORDS])
    ticket = started(service)
    service.turn(USER, ticket, speech())

    start, turn = (fields(line) for line in trace_lines(caplog))
    assert (start["phase"], start["entry"], start["language"], start["outcome"], start["turn"]) == (
        "start", "video", "en", "ok", "0")
    assert {"context_ms", "model_ms", "synth_ms"} <= start.keys() and "transcribe_ms" not in start
    assert (turn["phase"], turn["outcome"], turn["turn"], turn["next"], turn["correction"]) == (
        "turn", "ok", "1", "retry", "True")
    assert {"context_ms", "transcribe_ms", "model_ms", "synth_ms"} <= turn.keys()
    # One model call for the correction tool, one for the answer; the server detects the used words.
    assert turn["model_attempts"] == "2" and turn["used_items"] == "2" and turn["audio"] == "ready"
    assert int(turn["total_ms"]) >= int(turn["model_ms"])


def test_the_trace_never_contains_learner_reply_topic_item_or_identity_text(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    service = make_service(outputs=(turn_output(reply="Banana question?", reply_support="Câu hỏi chuối?"),
                                    turn_output(correction=CORRECTION, next="retry")), texts=[LEARNER_WORDS])
    ticket = started(service)
    service.turn(USER, ticket, speech())

    text = " ".join(trace_lines(caplog)).lower()
    assert trace_lines(caplog)
    for secret in ("secretcode", "banana", "chuối", "airport", "flying", "i like fly", "stressful",
                   str(OWNER), str(ITEM_ID), FLY.concept_id, ticket.lower(), "thử nói lại"):
        assert secret.lower() not in text


def test_failures_record_a_stable_code_and_the_attempts_not_the_message(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    bad = turn_output(reply="Yes " * 25)
    service = make_service(outputs=(turn_output(), *[bad] * 6), texts=[LEARNER_WORDS, LEARNER_WORDS])
    ticket = started(service)

    assert error_of(lambda: service.turn(USER, ticket, SpeechAudio(pcm_silence(2000))))[1] == "no_speech_detected"
    assert error_of(lambda: service.turn(USER, ticket, speech()))[1] == "companion_turn_unavailable"
    assert error_of(lambda: service.turn(USER, "not-a-ticket", speech()))[1] == "companion_session_invalid"

    _, silence, rejected, invalid = (fields(line) for line in trace_lines(caplog))
    assert silence["outcome"] == "no_speech_detected" and "model_ms" not in silence
    assert rejected["outcome"] == "companion_turn_unavailable"
    assert rejected["model_attempts"] == "6" and rejected["last_rejection"] == "rejected"
    assert invalid["outcome"] == "companion_session_invalid" and invalid["entry"] == "None"


def test_finish_emits_a_content_free_trace(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    service = make_service()
    ticket = started(service)
    service.finish(USER, ticket)

    finish = fields(trace_lines(caplog)[-1])
    assert finish["phase"] == "finish" and finish["entry"] == CompanionEntry.VIDEO.value
    assert finish["outcome"] == "ok" and "memory_ms" not in finish


def test_phase_timings_accumulate_across_attempts():
    trace = CompanionTrace(phase="turn")
    with trace.timed("model"):
        pass
    first = trace.phase_ms["model"]
    with trace.timed("model"):
        pass
    assert trace.phase_ms["model"] >= first
