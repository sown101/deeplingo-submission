import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.bootstrap.wiring.session_events import get_session_events_service
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.session_events import (
    ExtractedUses, LearnerTurn, SelectedWord, SessionEventsService, SessionText, UseCandidate,
    confirmed_uses,
)
from app.modules.learning.infrastructure.session_events import RedisSessionText
from app.modules.learning.infrastructure.session_event_queue import CelerySessionEventQueue
from app.modules.learning.worker import tasks
from app.modules.learning.application.learned_items import LearnedItem
from tests.learning.test_realtime_companion import (
    FakeChannel, TranscriptPiece, TurnComplete, ToolCall, auth, service as relay_service,
)
from tests.learning.test_companion import OWNER

NOW = datetime(2026, 10, 27, 8, tzinfo=UTC)
WORD = uuid4()


def sample(**changes):
    data = SessionText(id=uuid4(), user_id=OWNER, language_code="en", context_key="home:travel", ended_at=NOW,
        targets=[SelectedWord(concept_id=WORD, text="travel", meaning="go from one place to another", forms=["travel", "travelling"])],
        turns=[LearnerTurn(text="I travel with my family.")])
    return data.model_copy(update=changes)


def output(data, **changes):
    use = dict(concept_id=WORD, turn=0, quote=data.turns[0].text, used_form="travel",
               correct_usage=True, meaning_matches=True)
    use.update(changes)
    return ExtractedUses(uses=[UseCandidate(**use)])


class Store:
    def __init__(self):
        self.rows, self.ledger = {}, {}
    def create(self, data):
        if data.id in self.rows:
            return False
        self.rows[data.id] = {"user_id": str(data.user_id), "status": "queued", "events": [],
                              "expires_at": (data.ended_at + timedelta(seconds=900)).isoformat()}
        return True
    def get(self, sid, uid=None):
        row = self.rows.get(sid)
        return row if row and (uid is None or row["user_id"] == str(uid)) else None
    def claim(self, sid):
        row = self.rows.get(sid)
        if not row or row["status"] != "queued":
            return False
        row["status"] = "processing"
        return True
    def fail(self, sid, code):
        if sid in self.rows and self.rows[sid]["status"] in {"queued", "processing", "projecting"}:
            self.rows[sid]["status"] = "expired" if code == "expired" else "failed"
    def projected(self, sid):
        self.rows[sid]["status"] = "completed"
    def complete(self, sid, uses, model):
        events = [{**use, "text": "travel"} for use in uses]
        self.rows[sid].update(status="projecting", events=events)
        for use in uses:
            self.ledger[(sid, use["concept_id"])] = use
        return events


def harness(data=None):
    data = data or sample()
    store, text, queue, model, rungs = Store(), Mock(), Mock(), Mock(), Mock()
    text.get.return_value = data.model_dump_json()
    model.generate_structured.return_value = output(data)
    model.model_name = "fake-text-model"
    service = SessionEventsService(store=store, text=text, queue=queue, model=model, rungs=rungs, clock=lambda: NOW)
    return service, data


def test_one_analysis_per_session_is_idempotent_and_only_derived_evidence_is_durable():
    s, data = harness()
    assert s.submit(data)["status"] == "queued"
    assert s.submit(data)["status"] == "queued"
    s.queue.submit.assert_called_once_with(data.id)
    s.text.put.assert_called_once_with(data.id, data.model_dump_json(), 900)
    assert s.process(data.id) == {"status": "completed", "events": 1}
    assert s.process(data.id) == {"status": "not_claimed"}
    s.model.generate_structured.assert_called_once()
    s.rungs.refresh_rung.assert_called_once_with(OWNER, WORD, strict=True)
    assert s.store.ledger[(data.id, str(WORD))]["kind"] == "spontaneous_use"
    assert data.turns[0].text not in str(s.store.rows)
    assert s.result(OWNER, data.id)["events"][0]["text"] == "travel"
    s.text.delete.assert_called_with(data.id)


@pytest.mark.parametrize("assisted", [False, True])
def test_assistance_is_taken_from_the_server_turn_not_a_judge_label(assisted):
    data = sample(turns=[LearnerTurn(text="I travel with my family.", assisted_ids=[WORD] if assisted else [])])
    assert confirmed_uses(data, output(data))[0]["kind"] == ("framed_use" if assisted else "spontaneous_use")


@pytest.mark.parametrize("changes", [
    {"correct_usage": False}, {"meaning_matches": False},
])
def test_a_word_match_without_meaningful_correct_use_never_changes_progress(changes):
    s, data = harness()
    s.model.generate_structured.return_value = output(data, **changes)
    s.submit(data)
    assert s.process(data.id)["events"] == 0
    assert s.store.ledger == {}
    s.rungs.refresh_rung.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"concept_id": uuid4()}, {"turn": 7}, {"quote": "A fabricated learner answer."},
    {"used_form": "airplane"},
])
def test_foreign_unselected_fabricated_or_unsupported_model_evidence_is_rejected(changes):
    data = sample()
    assert confirmed_uses(data, output(data, **changes)) == []


def test_one_ungrounded_candidate_does_not_discard_the_sessions_real_uses():
    data = sample(); valid = output(data).uses[0]
    fabricated = output(data, concept_id=uuid4(), quote="A fabricated learner answer.").uses[0]
    assert [use["concept_id"] for use in confirmed_uses(data, ExtractedUses(uses=[fabricated, valid]))] == [str(WORD)]


def test_duplicate_concepts_in_model_output_are_rejected():
    data = sample(); candidate = output(data).uses[0]
    assert len(confirmed_uses(data, ExtractedUses(uses=[candidate, candidate]))) == 1


@pytest.mark.parametrize("data", [
    sample(targets=[SelectedWord(concept_id=WORD, text="travel", meaning=None, forms=["travel"])]),
    sample(turns=[LearnerTurn(text="I travel with my family.", truncated=True)]),
    sample(turns=[LearnerTurn(text="I travel with my family.", examples_seen=1)], examples=["I travel with my family."]),
])
def test_missing_sense_truncated_speech_and_copied_model_answers_do_not_receive_credit(data):
    assert confirmed_uses(data, output(data)) == []


def test_english_substrings_are_not_word_uses_and_chinese_uses_are_supported():
    data = sample(turns=[LearnerTurn(text="This travelogue is interesting.")])
    assert confirmed_uses(data, output(data)) == []
    zh = sample(language_code="zh", targets=[SelectedWord(concept_id=WORD,text="分享",meaning="to share",forms=["分享"])],
                turns=[LearnerTurn(text="我想分享这个故事。")])
    assert confirmed_uses(zh, output(zh, used_form="分享"))[0]["kind"] == "spontaneous_use"


@pytest.mark.parametrize("missing,seconds", [(True, 0), (False, 841)])
def test_expired_text_never_calls_a_provider_or_writes_evidence(missing, seconds):
    s, data = harness(); s.submit(data)
    if missing:
        s.text.get.return_value = None
    s.clock = lambda: NOW + timedelta(seconds=seconds)
    assert s.process(data.id)["status"] == "expired"
    s.model.generate_structured.assert_not_called()
    s.rungs.refresh_rung.assert_not_called()
    assert s.store.ledger == {}
    s.text.delete.assert_called_with(data.id)


def test_queue_failure_discards_text_and_repeated_submit_does_not_delete_a_running_payload():
    s, data = harness(); s.queue.submit.side_effect = RuntimeError("private detail")
    assert s.submit(data)["status"] == "unavailable"
    assert s.store.rows[data.id]["status"] == "failed"
    s.text.delete.assert_called_with(data.id)
    s2, second = harness(); s2.submit(second); s2.store.claim(second.id)
    s2.text.delete.reset_mock()
    assert s2.submit(second)["status"] == "processing"
    s2.text.delete.assert_not_called()


def test_provider_errors_are_not_learner_evidence_and_never_log_their_body(caplog):
    s, data = harness(); s.model.generate_structured.side_effect = RuntimeError("PRIVATE_LEARNER_REPLY")
    s.submit(data)
    assert s.process(data.id)["status"] == "failed"
    assert "PRIVATE_LEARNER_REPLY" not in caplog.text
    assert not s.store.ledger
    s.text.delete.assert_called_with(data.id)


def test_text_retention_is_absolute_and_does_not_restart_at_enqueue():
    s, data = harness(); s.clock = lambda: NOW + timedelta(seconds=120)
    s.submit(data)
    assert s.text.put.call_args.args[-1] == 780


def test_result_is_owned_and_queued_jobs_eventually_show_expired():
    s, data = harness(); s.submit(data)
    assert s.result(uuid4(), data.id) is None
    s.clock = lambda: NOW + timedelta(seconds=901)
    assert s.result(OWNER, data.id)["status"] == "expired"


@pytest.mark.parametrize("config,replication", [
    ({"appendonly":"yes","save":""},{"role":"master","connected_slaves":0}),
    ({"appendonly":"no","save":"900 1"},{"role":"master","connected_slaves":0}),
    ({"appendonly":"no","save":""},{"role":"master","connected_slaves":1}),
    ({"appendonly":"no","save":""},{"role":"slave"}),
])
def test_raw_text_is_refused_on_persistent_or_replicated_redis(config, replication):
    redis = Mock(); redis.config_get.return_value=config; redis.info.return_value=replication
    with pytest.raises(RuntimeError):
        RedisSessionText(redis).put(uuid4(), "PRIVATE_TEXT", 900)
    redis.set.assert_not_called()


def test_volatile_redis_gets_an_expiring_non_overwriting_value_only():
    redis = Mock(); redis.config_get.return_value={"appendonly":"no","save":""}
    redis.info.return_value={"role":"master","connected_slaves":0}; redis.set.return_value=True
    store=RedisSessionText(redis); sid=uuid4(); store.put(sid,"private",900)
    redis.set.assert_called_once_with(store.key(sid),"private",ex=900,nx=True)
    with pytest.raises(ValueError):store.put(sid,"private",901)


def test_celery_message_contains_only_a_session_id_and_has_an_expiry(monkeypatch):
    from app.modules.learning.infrastructure import session_event_queue
    celery=Mock();monkeypatch.setattr(session_event_queue,"celery_app",celery)
    sid=uuid4();CelerySessionEventQueue().submit(sid)
    args,kwargs=celery.send_task.call_args
    assert args==("deeplingo.extract_speaking_events",)
    assert kwargs["args"]==[str(sid)] and kwargs["expires"]==900 and kwargs["retry"] is False


def test_worker_is_bounded_and_dispatches_only_the_server_id(monkeypatch):
    from app.bootstrap.wiring import session_events as wiring
    processor=Mock();processor.process.return_value={"status":"completed","events":1}
    monkeypatch.setattr(wiring,"get_session_events_service",lambda:processor)
    sid=uuid4();assert tasks.extract_speaking_events(str(sid))["status"]=="completed"
    processor.process.assert_called_once_with(sid)
    assert tasks.extract_speaking_events.time_limit==60 and tasks.extract_speaking_events.max_retries==2


def test_http_analysis_result_never_exposes_another_learners_session():
    s,data=harness();s.submit(data)
    app.dependency_overrides[get_session_events_service]=lambda:s
    app.dependency_overrides[require_authenticated_user]=lambda:CurrentUser(id=uuid4())
    try:
        with TestClient(app) as client:
            assert client.get(f"/api/v1/v3/learner/me/speaking-sessions/{data.id}").status_code==404
        app.dependency_overrides[require_authenticated_user]=lambda:CurrentUser(id=OWNER)
        with TestClient(app) as client:
            response=client.get(f"/api/v1/v3/learner/me/speaking-sessions/{data.id}")
            assert response.status_code==200 and set(response.json())=={"session_id","status","events"}
    finally:
        app.dependency_overrides.pop(get_session_events_service,None)
        app.dependency_overrides.pop(require_authenticated_user,None)


def test_realtime_queues_analysis_for_a_consented_conversation_and_tracks_prior_support():
    async def scenario():
        relay=relay_service();processor=Mock();processor.submit.return_value={"session_id":str(uuid4()),"status":"queued"}
        relay.session_events=processor
        relay.setup.target_catalog=Mock()
        words=[LearnedItem(str(WORD),"travel","vocabulary","to journey","selected",("travel",))]
        relay.setup.target_catalog.select.return_value=words
        relay.setup.focus=Mock();relay.setup.focus.choose.return_value=SimpleNamespace(title="Travel",topic_id=None,items=words)
        channel=FakeChannel([auth(),("text",'{"type":"start","entry":"home"}')])
        task=asyncio.create_task(relay.run(channel))
        try:
            for _ in range(100):
                if relay.voice.opened:break
                await asyncio.sleep(.01)
            for event in [TranscriptPiece("learner","I travel with my family."),TurnComplete(),
                          ToolCall("hint1","show_hint",{"words":["travel"],"question":"Thử trả lời nhé?"}),
                          TranscriptPiece("learner","I travel every summer."),TurnComplete()]:
                await relay.voice.connection.events_queue.put(event)
            for _ in range(100):
                if channel.types().count("turn_complete")==2:break
                await asyncio.sleep(.01)
            await channel.inbound.put(("text",'{"type":"end"}'))
            await asyncio.wait_for(task,2)
            data=processor.submit.call_args.args[0]
            assert data.turns[0].assisted_ids==[] and data.turns[1].assisted_ids==[WORD]
            assert channel.json[-1]["analysis"]["status"]=="queued"
        finally:
            if not task.done():
                task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("interrupted", [False, True])
def test_barge_in_after_a_partial_spoken_cue_is_assisted_not_independent(interrupted):
    from app.modules.learning.application.agent.voice import VoiceSession, Interrupted
    from tests.learning.test_companion import USER, ITEM_ID
    relay=relay_service(); relay.setup.target_catalog=Mock()
    relay.setup.target_catalog.select.return_value=[LearnedItem(str(WORD),"travel","vocabulary","journey","selected",("travel",))]
    prepared=relay.setup.prepare_selected(USER,"video",ITEM_ID,[WORD])
    session=VoiceSession(user=USER,prepared=prepared,day=None,started=0,transient=True)
    channel=FakeChannel([])
    async def scenario():
        task=asyncio.create_task(relay._from_provider(channel,relay.voice.connection,session))
        events = [TranscriptPiece("companion","Do you travel")]
        if interrupted:
            events.append(Interrupted())
        events += [TranscriptPiece("learner","I travel every summer."),TurnComplete()]
        for event in events:
            await relay.voice.connection.events_queue.put(event)
        for _ in range(100):
            if channel.types().count("turn_complete")==1:break
            await asyncio.sleep(.01)
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())
    assert session.analysis_turns[0].assisted_ids==[WORD]


def test_an_incomplete_support_history_cannot_be_used_to_grant_credit():
    from app.modules.learning.application.agent.voice import VoiceSession
    from tests.learning.test_companion import USER, ITEM_ID
    relay=relay_service();prepared=relay.setup.prepare(USER,"video",ITEM_ID)
    session=VoiceSession(user=USER,prepared=prepared,day=None,started=0,transient=True)
    session.note_support("x"*601)
    assert session.support_truncated


def test_a_long_explanation_still_leaves_later_turns_their_evidence():
    from app.modules.learning.application.agent.voice import VoiceSession
    from tests.learning.test_companion import USER, ITEM_ID
    relay=relay_service();prepared=relay.setup.prepare(USER,"video",ITEM_ID)
    session=VoiceSession(user=USER,prepared=prepared,day=None,started=0,transient=True)
    explanation="Thì quá khứ đơn dùng cho việc đã xong. "*10
    session.note_support(explanation)
    assert not session.support_truncated and session.examples==[" ".join(explanation.split())]


@pytest.mark.parametrize("assisted,expected_rung", [(True,3),(False,4)])
def test_confirmed_session_use_updates_the_existing_l1_ladder_without_activating_backlog(assisted,expected_rung):
    from tests.learner.test_word_targets import build, add_backlog, USER_ID
    env=build();word=add_backlog(env,1)[0]
    env.targets.rows[word.id].update(status="backlog",activated_at=None)  # a legacy row remains untouched
    data=sample(user_id=USER_ID,targets=[SelectedWord(concept_id=word.id,text="travel",meaning="to journey",forms=["travel"])],
                turns=[LearnerTurn(text="I travel with my family.",assisted_ids=[word.id] if assisted else [])])
    s,_=harness(data)
    s.rungs=env.service
    s.model.generate_structured.return_value=output(data,concept_id=word.id)
    original_complete=s.store.complete
    def complete(sid,uses,model):
        result=original_complete(sid,uses,model)
        for use in result:
            env.events.record(USER_ID,concept_id=word.id,kind=use["kind"],outcome="correct",event_key=f"l2:{sid}:{word.id}",occurred_at=NOW,context_key="home:travel")
        return result
    s.store.complete=complete
    s.submit(data);assert s.process(data.id)["status"]=="completed"
    assert env.targets.rows[word.id]["rung"]==expected_rung
    assert env.targets.rows[word.id]["status"]=="backlog"


def test_projection_failure_replays_durable_events_without_repeating_the_model():
    s,data=harness();s.submit(data)
    s.rungs.refresh_rung.side_effect=RuntimeError("temporary database failure")
    assert s.process(data.id)["status"]=="projection_pending"
    assert s.store.rows[data.id]["status"]=="projecting" and len(s.store.ledger)==1
    s.text.get.reset_mock();s.rungs.refresh_rung.side_effect=None
    assert s.process(data.id)=={"status":"completed","events":1}
    s.text.get.assert_not_called()
    s.model.generate_structured.assert_called_once()
    assert len(s.store.ledger)==1


def test_word_use_keeps_its_observed_time_instead_of_the_end_or_analysis_time():
    observed=NOW-timedelta(minutes=3)
    data=sample(turns=[LearnerTurn(text="I travel with my family.",occurred_at=observed)])
    assert confirmed_uses(data,output(data))[0]["occurred_at"]==observed.isoformat()
    data.turns[0].occurred_at=NOW+timedelta(days=3)
    assert confirmed_uses(data,output(data))==[]


def test_worker_retries_only_projection_and_bounds_the_number_of_retries(monkeypatch):
    from app.bootstrap.wiring import session_events as wiring
    from celery.exceptions import Retry
    processor=Mock();processor.process.return_value={"status":"projection_pending"}
    monkeypatch.setattr(wiring,"get_session_events_service",lambda:processor)
    retry=Mock(side_effect=Retry());monkeypatch.setattr(tasks.extract_speaking_events,"retry",retry)
    sid=uuid4();tasks.extract_speaking_events.push_request(retries=0)
    try:
        with pytest.raises(Retry):tasks.extract_speaking_events.run(str(sid))
        retry.assert_called_once_with(countdown=5)
        processor.fail_projection.assert_not_called()
    finally:tasks.extract_speaking_events.pop_request()
    tasks.extract_speaking_events.push_request(retries=2)
    try:
        assert tasks.extract_speaking_events.run(str(sid))["status"]=="failed"
        processor.fail_projection.assert_called_once_with(sid)
    finally:tasks.extract_speaking_events.pop_request()


def test_a_consent_revoked_while_queued_stops_the_model_call_and_discards_the_text():
    s, data = harness()
    s.consent = Mock()
    s.consent.has_consent.return_value = False
    s.submit(data)
    assert s.process(data.id) == {"status": "failed"}
    s.model.generate_structured.assert_not_called()
    s.text.delete.assert_called_with(data.id)
    assert s.store.ledger == {}


def test_a_consent_revoked_during_the_model_call_writes_no_evidence():
    s, data = harness()
    s.consent = Mock()
    s.consent.has_consent.side_effect = [True, False]
    s.submit(data)
    assert s.process(data.id) == {"status": "failed"}
    assert s.store.ledger == {}
    s.text.delete.assert_called_with(data.id)
