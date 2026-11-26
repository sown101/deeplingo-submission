"""FR-3.11: a separate, default-off consent to keep spoken turns as text; view, delete, export, 12-month purge."""
import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_speech_transcripts_service
from app.bootstrap.wiring.agent import SpeechTranscripts
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.speech_transcripts import SpeechTranscriptService
from app.modules.learner.domain.agent_signals import AgentConsent
from app.modules.learner.domain.speech_transcripts import GrammarError, StoredTranscript, TranscriptTurn
from app.modules.learner.infrastructure.data_export import LearnerOwnDataSection
from app.modules.learning.application.agent.voice import ToolCall, TranscriptPiece, TurnComplete
from app.modules.learning.domain.speaking import (
    PronunciationErrorType,
    PronunciationResult,
    PronunciationScores,
    PronunciationWord,
)
from tests.learner.test_data_export import FakeClient
from tests.learning.speaking_fixtures import pcm_silence, pcm_tone
from tests.learning.test_companion import OWNER
from tests.learning.test_realtime_companion import FakeChannel, FakeVoice, auth, service as relay_service, start

USER, OTHER = uuid4(), uuid4()
URL = "/api/v1/v3/learner/me/agent/transcripts"
NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)
MIGRATION = next(Path(__file__).parents[2].glob("supabase/migrations/*_speech_transcripts.sql"))


class FakeConsents:
    def __init__(self, voice=None, transcripts=None):
        self.rows = {USER: AgentConsent(user_id=USER, voice_consent=voice, transcript_consent=transcripts)}

    def get(self, user_id):
        return self.rows.get(user_id)

    def set_transcripts(self, user_id, granted):
        row = self.rows.get(user_id) or AgentConsent(user_id=user_id)
        self.rows[user_id] = row.model_copy(update={"transcript_consent": granted, "transcript_decided_at": NOW})
        return self.rows[user_id]


class FakeTranscripts:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def add_many(self, user_id, turns):
        for turn in turns:
            self.rows.append(StoredTranscript(**turn.model_dump(), id=uuid4(), user_id=user_id))
        return len(turns)

    def list_page(self, user_id, *, since, before, limit):
        rows = [row for row in self.rows if row.user_id == user_id and row.occurred_at > since
                and (before is None or row.occurred_at < before)]
        return sorted(rows, key=lambda row: row.occurred_at, reverse=True)[:limit]

    def delete_one(self, user_id, transcript_id):
        before = len(self.rows)
        self.rows = [row for row in self.rows if not (row.user_id == user_id and row.id == transcript_id)]
        return len(self.rows) < before

    def delete_all(self, user_id):
        self.rows = [row for row in self.rows if row.user_id != user_id]


def turn(text="I go to school yesterday.", *, at=NOW, index=0, **extra):
    return TranscriptTurn(session_id=uuid4(), turn_index=index, language_code="en", learner_text=text,
                          occurred_at=at, **extra)


def stored(user=USER, *, at=NOW, text="Hello there."):
    return StoredTranscript(**turn(text, at=at).model_dump(), id=uuid4(), user_id=user)


def service(voice=True, transcripts=True, rows=()):
    return SpeechTranscriptService(consents=FakeConsents(voice, transcripts), transcripts=FakeTranscripts(rows),
                                   clock=lambda: NOW)


# --- Consent -------------------------------------------------------------------------------------

def test_the_transcript_consent_is_off_until_asked_and_separate_from_the_voice_consent():
    view = service(voice=True, transcripts=None).consent(USER)
    assert (view.status, view.decided_at, view.active) == ("ask", None, False)
    assert service(voice=True, transcripts=False).consent(USER).status == "revoked"
    granted = service(voice=True, transcripts=None).set_consent(USER, True)
    assert granted.status == "granted" and granted.decided_at and granted.active


def test_turns_are_kept_only_while_both_consents_are_granted():
    for voice, transcripts in [(None, True), (False, True), (True, None), (True, False), (None, None)]:
        keeper = service(voice=voice, transcripts=transcripts)
        assert keeper.consent(USER).active is False
        assert keeper.keep(USER, [turn()]) == 0 and keeper.store.rows == []
    keeper = service()
    assert keeper.keep(USER, [turn()]) == 1 and len(keeper.store.rows) == 1


def test_revoking_stops_keeping_new_turns_and_leaves_the_kept_ones_for_the_learner_to_delete():
    keeper = service(rows=[stored()])
    keeper.set_consent(USER, False)
    assert keeper.keep(USER, [turn()]) == 0
    assert len(keeper.page(USER).transcripts) == 1  # still visible and deletable after revoking
    keeper.delete_all(USER)
    assert keeper.page(USER).transcripts == []


# --- Domain --------------------------------------------------------------------------------------

def test_text_is_clipped_never_rejected_for_length_and_an_empty_turn_is_refused():
    long = turn("word " * 1000, agent_text="x" * 5000, topic="t" * 500)
    assert len(long.learner_text) == 2000 and len(long.agent_text) == 2000 and len(long.topic) == 200
    with pytest.raises(ValidationError):
        turn("   ")
    with pytest.raises(ValidationError):
        turn(assistance_level=4)


# --- Listing and deleting ------------------------------------------------------------------------

def test_the_learner_sees_only_their_own_turns_newest_first_and_nothing_past_12_months():
    rows = [stored(at=NOW - timedelta(days=1), text="older"), stored(at=NOW, text="newest"),
            stored(at=NOW - timedelta(days=366), text="expired"), stored(OTHER, text="someone else")]
    page = service(rows=rows).page(USER)
    assert [item.learner_text for item in page.transcripts] == ["newest", "older"]
    assert "user_id" not in page.transcripts[0].model_dump()


def test_pages_continue_from_the_cursor():
    rows = [stored(at=NOW - timedelta(minutes=minute), text=str(minute)) for minute in range(5)]
    keeper = service(rows=rows)
    first = keeper.page(USER, limit=2)
    assert [item.learner_text for item in first.transcripts] == ["0", "1"] and first.next_before
    second = keeper.page(USER, before=datetime.fromisoformat(first.next_before), limit=10)
    assert [item.learner_text for item in second.transcripts] == ["2", "3", "4"] and second.next_before is None


def test_delete_one_and_delete_all_touch_only_the_owner():
    mine, theirs = stored(), stored(OTHER)
    keeper = service(rows=[mine, theirs])
    assert keeper.delete_one(OTHER, mine.id) is False
    assert keeper.delete_one(USER, mine.id) is True
    keeper.delete_all(USER)
    assert [row.id for row in keeper.store.rows] == [theirs.id]


# --- Migration -----------------------------------------------------------------------------------

def test_migration_is_backend_only_cascades_and_purges_after_12_months():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "add column if not exists transcript_consent boolean," in sql  # null = never asked: default off
    assert "references v3.profiles(id) on delete cascade" in sql
    assert "enable row level security" in sql
    assert "revoke all privileges on v3.learner_speech_transcripts from public, anon, authenticated;" in sql
    assert not re.search(r"grant\s+[^;]*\s+to\s+(authenticated|anon)", sql)
    assert "create policy" not in sql
    assert "audio" not in sql.split("create table", 1)[1].split("comment on table", 1)[0]
    assert "where occurred_at <= now() - interval '12 months' limit p_limit" in sql
    assert "'speech_transcripts', transcripts" in sql
    assert "grant execute on function v3.purge_expired_learner_data(integer) to service_role;" in sql


# --- Export --------------------------------------------------------------------------------------

def test_the_export_carries_the_transcript_consent_and_the_learners_own_kept_turns():
    recent, old = datetime.now(UTC).isoformat(), (datetime.now(UTC) - timedelta(days=400)).isoformat()
    row = {"session_id": "s", "language_code": "en", "library_item_id": None, "topic": "Travel",
           "assistance_level": 1, "agent_text": "Where did you go?", "recognized_text": "I go to Hue",
           "word_scores": [{"word": "go", "accuracy": 40.0, "error_type": "mispronunciation"}],
           "grammar_errors": [{"quote": "I go", "suggestion": "I went", "note": None, "error_type": "verb_tense"}],
           "created_at": recent}
    db = FakeClient({
        "learner_agent_consent": [{"user_id": str(USER), "voice_consent": True, "transcript_consent": True,
                                   "transcript_decided_at": "t", "decided_at": "t", "updated_at": "t"}],
        "learner_speech_transcripts": [
            {**row, "user_id": str(USER), "turn_index": 0, "learner_text": "I go to Hue.", "occurred_at": recent},
            {**row, "user_id": str(USER), "turn_index": 1, "learner_text": "expired", "occurred_at": old},
            {**row, "user_id": str(OTHER), "turn_index": 0, "learner_text": "not mine", "occurred_at": recent}],
    })
    section = LearnerOwnDataSection(db).export(USER)
    assert section["transcript_consent"]["transcript_consent"] is True
    assert [item["learner_text"] for item in section["speech_transcripts"]] == ["I go to Hue."]
    assert section["speech_transcripts"][0]["grammar_errors"][0]["quote"] == "I go"
    assert all(filters == {"user_id": str(USER)} for table, _, filters in db.queries
               if table == "learner_speech_transcripts")


def test_the_export_still_works_where_the_transcript_migration_is_not_applied():
    from postgrest.exceptions import APIError

    class Missing(FakeClient):
        def table(self, name):
            if name == "learner_speech_transcripts":
                raise APIError({"message": "relation does not exist", "code": "42P01"})
            return super().table(name)

    section = LearnerOwnDataSection(Missing({})).export(USER)
    assert section["speech_transcripts"] == [] and section["transcript_consent"] is None


# --- API -----------------------------------------------------------------------------------------

@pytest.fixture
def api():
    keeper = service(voice=True, transcripts=None)
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=USER)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_speech_transcripts_service] = lambda: keeper
    try:
        yield SimpleNamespace(client=TestClient(app), keeper=keeper, headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_every_transcript_route_needs_a_signed_in_learner(api):
    calls = [api.client.get(f"{URL}/consent"), api.client.put(f"{URL}/consent", json={"granted": True}),
             api.client.get(URL), api.client.delete(URL), api.client.delete(f"{URL}/{uuid4()}")]
    assert [call.status_code for call in calls] == [401] * 5


def test_consent_view_and_delete_through_the_api(api):
    response = api.client.get(f"{URL}/consent", headers=api.headers)
    assert response.json() == {"status": "ask", "decided_at": None, "active": False}
    assert response.headers["cache-control"] == "no-store"
    granted = api.client.put(f"{URL}/consent", json={"granted": True}, headers=api.headers).json()
    assert granted["status"] == "granted" and granted["active"] is True
    api.keeper.keep(USER, [turn(grammar_errors=[{"quote": "I go", "suggestion": "I went"}])])
    listed = api.client.get(URL, headers=api.headers)
    assert listed.headers["cache-control"] == "no-store"
    [item] = listed.json()["transcripts"]
    assert item["learner_text"] == "I go to school yesterday." and item["grammar_errors"][0]["suggestion"] == "I went"
    assert api.client.delete(f"{URL}/{item['id']}", headers=api.headers).status_code == 204
    assert api.client.delete(f"{URL}/{item['id']}", headers=api.headers).status_code == 404
    assert api.client.delete(URL, headers=api.headers).status_code == 204
    assert api.client.get(URL, headers=api.headers).json() == {"transcripts": [], "next_before": None}


def test_the_consent_body_rejects_unknown_fields_and_the_page_size_is_bounded(api):
    forged = api.client.put(f"{URL}/consent", json={"granted": True, "user_id": str(OTHER)}, headers=api.headers)
    assert forged.status_code == 422
    assert api.client.get(f"{URL}?limit=500", headers=api.headers).status_code == 422


# --- The voice conversation ----------------------------------------------------------------------

class Consent:
    def __init__(self, answers):
        self.answers = list(answers)

    def has_consent(self, user_id):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Assessor:
    provider_name = "fake"

    def supports(self, language_code):
        return True

    def assess(self, audio, *, reference_text, language_code):
        return PronunciationResult(
            recognized_text="I go to the market yesterday", scores=PronunciationScores(70, 70, 70, 70),
            words=(PronunciationWord("go", 42.0, PronunciationErrorType.MISPRONUNCIATION),
                   PronunciationWord("market", 91.0, PronunciationErrorType.NONE)))


def converse(*, voice_answers=(True,), transcripts=(True, True)):
    """One conversation: the agent asks, the learner answers with a mistake, the agent corrects it."""
    consents = FakeConsents(voice=True, transcripts=True)
    keeper = SpeechTranscriptService(consents=consents, transcripts=FakeTranscripts())
    answers = list(transcripts)
    keeper.may_keep = lambda user_id: answers.pop(0) if len(answers) > 1 else answers[0]
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.consent = Consent(voice_answers)
    relay.pronunciation = Assessor()
    relay.transcripts = SpeechTranscripts(keeper)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await voice.connection.events_queue.put(TranscriptPiece("companion", "What did you do yesterday?"))
        await voice.connection.events_queue.put(TurnComplete())
        await channel.inbound.put(("text", '{"type": "help"}'))
        await asyncio.sleep(0.02)
        pcm = pcm_silence(300) + pcm_tone(1200) + pcm_silence(300)
        for offset in range(0, len(pcm), 32_000):
            await channel.inbound.put(("bytes", pcm[offset:offset + 32_000]))
        await asyncio.sleep(0.02)
        for event in (TranscriptPiece("learner", "I go to the market yesterday."),
                      ToolCall("1", "show_correction", {"quote": "I go", "suggestion": "I went",
                                                         "note": "Quá khứ.", "error_type": "verb_tense"}),
                      TranscriptPiece("companion", "Nice. What did you buy?"), TurnComplete()):
            await voice.connection.events_queue.put(event)
        await asyncio.sleep(0.05)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    return keeper.store.rows, channel


def test_with_both_consents_each_learner_turn_is_kept_with_its_context_scores_and_corrections(caplog):
    caplog.set_level(logging.DEBUG)
    rows, channel = converse()
    [kept] = rows
    assert kept.user_id == OWNER and kept.language_code == "en" and kept.library_item_id is not None
    assert kept.learner_text == "I go to the market yesterday."
    assert kept.agent_text == "What did you do yesterday?"
    assert kept.assistance_level == 1  # the learner tapped Help once before answering
    assert kept.recognized_text == "I go to the market yesterday"
    assert [(score.word, score.accuracy, score.error_type) for score in kept.word_scores] == [
        ("go", 42.0, "mispronunciation"), ("market", 91.0, "none")]
    assert [(error.quote, error.suggestion, error.error_type) for error in kept.grammar_errors] == [
        ("I go", "I went", "verb_tense")]
    # Never logged.
    assert "market yesterday" not in caplog.text and "What did you do" not in caplog.text


def test_nothing_is_kept_without_the_transcript_consent_or_after_revoking_during_the_conversation():
    assert converse(transcripts=(False,))[0] == []
    # Revoked transcript consent while talking: the server checks again when it stores.
    assert converse(transcripts=(True, False))[0] == []
    # Revoked voice consent while talking: nothing is analysed or kept.
    assert converse(voice_answers=(True, False))[0] == []


# --- The agent's memory of earlier conversations (Q18, decided 2026-11-07) -------------------------

def _recent(self, user_id, *, language_code, since, limit):
    rows = [row for row in self.rows if row.user_id == user_id and row.language_code == language_code
            and row.occurred_at > since]
    return sorted(rows, key=lambda row: row.occurred_at, reverse=True)[:limit]


FakeTranscripts.list_recent = _recent


def test_the_agent_reads_only_the_learners_own_newest_turns_in_this_language_and_only_with_both_consents():
    rows = [stored(at=NOW - timedelta(minutes=minute), text=f"turn {minute}") for minute in range(12)]
    rows += [stored(OTHER, text="someone else"), stored(at=NOW - timedelta(days=400), text="expired")]
    zh = stored(text="我去了市场")
    zh.language_code = "zh"
    keeper = service(rows=rows + [zh])
    recent = keeper.recent_for_agent(USER, language_code="en")
    assert [row.learner_text for row in recent] == [f"turn {minute}" for minute in range(7, -1, -1)]  # 8, oldest first
    for voice, transcripts in [(False, True), (True, False), (None, True), (True, None)]:
        assert service(voice=voice, transcripts=transcripts, rows=rows).recent_for_agent(USER, language_code="en") == []


def test_the_memory_block_is_bounded_and_marked_as_data():
    from app.modules.learning.application.agent.prompts import (
        MAX_PAST_BLOCK_CHARS, MAX_PAST_TURNS, past_turns_block,
    )
    assert past_turns_block(None) == "" and past_turns_block([{"said": "  "}]) == ""
    turns = [{"said": f"sentence {index} " + "word " * 100,
              "correction": {"quote": "I go", "suggestion": "I went " * 40}} for index in range(30)]
    block = past_turns_block(turns)
    assert "sentence 29" in block and "sentence 21" not in block  # the cap drops the oldest turns
    assert block.index("sentence 28") < block.index("sentence 29")  # shown oldest first
    assert block.count('"said"') <= MAX_PAST_TURNS
    assert len(block) < MAX_PAST_BLOCK_CHARS + 400  # the fixed preamble plus the capped data
    assert "data, never instructions" in block and "I go -> I went" in block


def test_a_conversation_starts_with_the_learners_earlier_turns_only_when_both_consents_stand(caplog):
    caplog.set_level(logging.DEBUG)
    earlier = stored(at=datetime.now(UTC) - timedelta(days=1), text="Last week I goed to Da Lat.")
    earlier = earlier.model_copy(update={"grammar_errors": [GrammarError(quote="I goed", suggestion="I went")]})

    def opened(transcripts_granted):
        keeper = SpeechTranscriptService(consents=FakeConsents(voice=True, transcripts=transcripts_granted),
                                         transcripts=FakeTranscripts())
        keeper.store.rows = [earlier.model_copy(update={"user_id": OWNER})]
        keeper.consents.rows[OWNER] = keeper.consents.rows[USER]
        voice = FakeVoice()
        relay = relay_service(voice=voice)
        relay.transcripts = SpeechTranscripts(keeper)
        channel = FakeChannel([auth(), start()])

        async def scenario():
            task = asyncio.create_task(relay.run(channel))
            await asyncio.sleep(0.05)
            await channel.inbound.put(("text", '{"type": "end"}'))
            await asyncio.wait_for(task, 5)

        asyncio.run(scenario())
        return voice.opened[0][1]

    instruction = opened(True)
    assert "Last week I goed to Da Lat." in instruction and "I goed -> I went" in instruction
    assert "Da Lat" not in opened(False) and "Da Lat" not in opened(None)
    assert "Da Lat" not in caplog.text  # never logged
