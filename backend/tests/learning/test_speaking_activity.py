"""FR-4.2: every speaking session counts towards the streak: a conversation and Shadowing.

Since 2026-11-18 (owner: one learning log) the fact lives in the learning log row of the practice: when,
language, which kind, how long; never what the learner said."""
import asyncio
from unittest.mock import Mock

import pytest

from app.modules.identity.contracts import CurrentUser
from tests.learning.test_companion import OWNER
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, TranscriptPiece, TurnComplete, auth, service as relay_service, start,
)
from tests.learning.test_speaking_services_and_api import (  # noqa: F401  (fixtures and builders)
    OWNER as SPEAKER, shadowing, speech,
)


def entries(log, kind):
    return [call.args[0] for call in log.record.call_args_list if call.args[0].kind == kind]


# --- Shadowing --------------------------------------------------------------------------

def test_a_scored_shadowing_attempt_logs_its_seconds_and_a_failed_one_logs_nothing(shadowing):
    shadowing.service.learning_log = Mock()
    shadowing.service.assess(CurrentUser(id=SPEAKER), shadowing.item, shadowing.segment_id, speech())
    [row] = entries(shadowing.service.learning_log, "shadowing")
    assert row.user_id == SPEAKER and row.language_code == "en" and row.detail["seconds"] == 2
    shadowing.service.learning_log.reset_mock()
    shadowing.assessor.outcome = RuntimeError("down")
    with pytest.raises(Exception):
        shadowing.service.assess(CurrentUser(id=SPEAKER), shadowing.item, shadowing.segment_id, speech())
    shadowing.service.learning_log.record.assert_not_called()


def test_a_failing_learning_log_never_breaks_shadowing(shadowing):
    shadowing.service.learning_log = Mock()
    shadowing.service.learning_log.record.side_effect = RuntimeError("database down")
    view = shadowing.service.assess(CurrentUser(id=SPEAKER), shadowing.item, shadowing.segment_id, speech())
    assert view.band


# --- The conversation ----------------------------------------------------------------------------

def run_conversation(*, turns, log, consent=None):
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.learning_log = log
    if consent is not None:
        relay.consent = consent
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for text in turns:
            for event in (TranscriptPiece("learner", text), TurnComplete()):
                await voice.connection.events_queue.put(event)
            await asyncio.sleep(0.04)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 3)

    asyncio.run(scenario())
    return channel


def test_a_conversation_where_the_learner_spoke_is_logged_once_without_what_was_said():
    log = Mock()
    run_conversation(turns=["I like to fly.", "Every summer."], log=log)
    [row] = entries(log, "speaking_session")
    assert row.user_id == OWNER and row.language_code == "en" and row.detail["channel"] == "voice"
    assert row.detail["turns"] == 2 and row.detail["reuse_words"] == [] and "fly" not in str(row)


def test_a_conversation_where_the_learner_said_nothing_is_not_logged():
    log = Mock()
    run_conversation(turns=[], log=log)
    assert entries(log, "speaking_session") == []


def test_a_revoked_consent_or_a_failing_log_changes_nothing_for_the_learner():
    class Revoked:
        calls = 0

        def has_consent(self, user_id):
            Revoked.calls += 1
            return Revoked.calls == 1  # granted at the start, revoked by the end
    log = Mock()
    run_conversation(turns=["I like to fly."], log=log, consent=Revoked())
    assert entries(log, "speaking_session") == []
    broken = Mock()
    broken.record.side_effect = RuntimeError("down")
    channel = run_conversation(turns=["I like to fly."], log=broken)
    assert channel.json[-1]["type"] == "ended"
