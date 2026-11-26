from pathlib import Path
from uuid import UUID, uuid4
from unittest.mock import Mock

from app.modules.learning.application.session_events import TEXT_TTL_SECONDS
from app.modules.learning.infrastructure.session_events import SpeakingSessionRepository
from app.modules.learning.infrastructure.data_export import LearningDataSection
from tests.learner.test_data_export import FakeClient, USER, OTHER


def test_speaking_export_is_owned_and_has_no_raw_transcript_quote_or_provider_diagnostics():
    db=FakeClient({"speaking_sessions":[
        {"id":str(uuid4()),"user_id":USER,"language_code":"zh","status":"completed","events":[],"targets":[]},
        {"id":str(uuid4()),"user_id":OTHER,"language_code":"en","status":"completed","events":[],"targets":[]},
    ]})
    section=LearningDataSection(db).export(UUID(USER))
    assert len(section["speaking_sessions"])==1
    assert section["speaking_sessions"][0]["language_code"]=="zh"
    columns,filters=next((cols,filters) for table,cols,filters in db.queries if table=="speaking_sessions")
    assert filters=={"user_id":USER}
    assert all(word not in columns for word in ("transcript","audio","quote","judge"))


def test_repository_owner_filter_and_atomic_claim_are_explicit():
    client=Mock();query=client.schema.return_value.table.return_value
    query.limit.return_value.execute.return_value.data=[]
    query.select.return_value=query;query.eq.return_value=query;query.update.return_value=query
    repo=SpeakingSessionRepository(client);sid,uid=uuid4(),uuid4()
    repo.get(sid,uid)
    assert ("user_id",str(uid)) in [call.args for call in query.eq.call_args_list]
    query.eq.reset_mock();query.execute.return_value.data=[{"id":str(sid)}]
    assert repo.claim(sid)
    assert ("status","queued") in [call.args for call in query.eq.call_args_list]


def test_forward_migration_protects_ownership_and_commits_only_eligible_selected_word_uses():
    path=Path(__file__).resolve().parents[2]/"supabase/migrations/20261026200927_l2_session_events.sql"
    sql=path.read_text(encoding="utf-8").lower()
    assert "enable row level security" in sql
    assert "for select to authenticated using ((select auth.uid()) = user_id)" in sql
    assert "security invoker" in sql and "security definer" not in sql
    assert "from public, anon, authenticated" in sql and "to service_role" in sql
    assert "sc.user_id = s.user_id" in sql and "sc.status in ('active', 'backlog')" in sql
    assert "v3.learner_known_concepts" in sql and "c.language_code = s.language_code" in sql
    assert "on conflict (user_id, event_key) do nothing" in sql
    assert "if s.status in ('projecting', 'completed') then return s.events" in sql
    assert "interval '15 minutes'" in sql and TEXT_TTL_SECONDS==900
    create=sql.split("create table v3.speaking_sessions (",1)[1].split(");",1)[0]
    assert all(word not in create for word in ("transcript", "audio", "quote"))
