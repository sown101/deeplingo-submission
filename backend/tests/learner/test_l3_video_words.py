"""L3 scopes saved word progress to an owned video without changing learning evidence."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_my_words_service
from app.main import app
from app.modules.learner.application.my_words import MyWordsError, SaveFromDictionary, SaveFromLookup, SaveFromOccurrence
from app.modules.learner.infrastructure.data_export import LearnerOwnDataSection
from app.modules.learner.infrastructure.video_words import VideoWordRepository
from tests.learner.test_my_words import USER, ITEM, me, service
from tests.learner.test_data_export import FakeClient


class Links:
    def __init__(self):
        self.owned={(USER,ITEM)}
        self.rows=set()
    def for_video(self,user_id,item):
        return {cid for uid,vid,cid in self.rows if (uid,vid)==(user_id,item)} if (user_id,item) in self.owned else None
    def add(self,user_id,item,cid):
        assert (user_id,item) in self.owned
        self.rows.add((user_id,item,cid))


@pytest.mark.parametrize("source",["lookup","occurrence"])
def test_saving_a_video_word_links_only_the_server_resolved_concept_and_retries_are_idempotent(source):
    words,resolved=service();links=Links();words.video_words=links
    request=(SaveFromOccurrence(source=source,library_item_id=ITEM,learning_object_id=uuid4()) if source=="occurrence"
        else SaveFromLookup(source=source,library_item_id=ITEM,segment_id=uuid4(),start_codepoint=0,end_codepoint=3))
    words.save(me(),request);words.save(me(),request)
    assert links.rows=={(USER,ITEM,resolved.id)} and len(words.saved.rows)==1
    assert words.list(me(),"en",ITEM).words[0].concept_id==resolved.id


def test_dictionary_saves_remain_global_without_inventing_a_video_source():
    words,resolved=service();words.video_words=Links()
    words.save(me(),SaveFromDictionary(source="dictionary",language_code="en",entry_id=uuid4(),sense_id="s"))
    assert not words.video_words.rows and len(words.list(me(),"en").words)==1
    assert words.list(me(),"en",ITEM).words==[]


def test_content_ownership_failure_never_creates_a_video_link_or_saves_a_word():
    words,_=service();words.video_words=Links()
    error=ValueError("Video not found");error.status_code=404;error.code="library_item_not_found"
    words.resolver.from_occurrence.side_effect=error
    with pytest.raises(MyWordsError):words.save(me(),SaveFromOccurrence(source="occurrence",library_item_id=uuid4(),learning_object_id=uuid4()))
    assert not words.video_words.rows and not words.saved.rows


def test_foreign_and_missing_video_have_the_same_404_before_reading_global_words():
    words,_=service();words.video_words=Links();words.saved=Mock()
    for item in [uuid4(),uuid4()]:
        with pytest.raises(MyWordsError) as result:words.list(me(),"en",item)
        assert result.value.status_code==404 and result.value.code=="library_item_not_found"
    words.saved.list_for_user.assert_not_called()


def test_another_users_links_never_enter_the_current_video_word_list():
    words,resolved=service();links=Links();words.video_words=links
    words.save(me(),SaveFromDictionary(source="dictionary",language_code="en",entry_id=uuid4(),sense_id="s"))
    links.rows.add((uuid4(),ITEM,resolved.id))
    assert words.list(me(),"en",ITEM).words==[]
    links.add(USER,ITEM,resolved.id)
    assert len(words.list(me(),"en",ITEM).words)==1


@pytest.mark.parametrize("status", ["active", "backlog", "suspended"])
def test_progress_is_the_current_server_rung_and_legacy_backlog_is_read_as_active(status):
    words,resolved=service();words.video_words=Links()
    words.save(me(),SaveFromOccurrence(source="occurrence",library_item_id=ITEM,learning_object_id=uuid4()))
    words.saved.rows[resolved.id].update(rung=3,status=status)
    view=words.list(me(),"en",ITEM).words[0]
    assert view.rung==3 and view.status==("active" if status=="backlog" else status)
    assert words.saved.rows[resolved.id]["status"]==status
    assert words.list(me(),"zh",ITEM).words==[]


def test_unconfigured_video_filter_fails_closed_while_global_reads_keep_working():
    words,_=service()
    assert words.list(me()).words==[]
    with pytest.raises(MyWordsError) as result:words.list(me(),"en",ITEM)
    assert result.value.code=="video_words_unavailable"


@pytest.fixture
def api():
    words,resolved=service();words.video_words=Links()
    verifier=Mock();verifier.verify.return_value=me()
    app.dependency_overrides[get_jwt_verifier]=lambda:verifier
    app.dependency_overrides[get_my_words_service]=lambda:words
    try:yield SimpleNamespace(client=TestClient(app),words=words,headers={"Authorization":"Bearer synthetic.user.jwt"})
    finally:app.dependency_overrides.clear()


def test_existing_words_route_authenticates_and_validates_the_video_selector(api):
    url="/api/v1/v3/learner/me/words"
    assert api.client.get(url,params={"library_item_id":str(ITEM)}).status_code==401
    assert api.client.get(url,params={"library_item_id":"bad"},headers=api.headers).status_code==422
    assert api.client.get(url,params={"library_item_id":str(uuid4())},headers=api.headers).status_code==404
    assert api.client.get(url,params={"library_item_id":str(ITEM)},headers=api.headers).json()["words"]==[]
    body={"source":"occurrence","library_item_id":str(ITEM),"learning_object_id":str(uuid4())}
    assert api.client.post(url,json=body,headers=api.headers).status_code==200
    assert len(api.client.get(url,params={"library_item_id":str(ITEM)},headers=api.headers).json()["words"])==1


def test_new_video_links_are_in_the_owned_export_without_speech_or_transcripts():
    other=str(uuid4());uid=str(USER);cid=str(uuid4())
    db=FakeClient({"learner_video_words":[{"user_id":uid,"library_item_id":str(ITEM),"concept_id":cid,"created_at":"t"},
        {"user_id":other,"library_item_id":str(ITEM),"concept_id":str(uuid4()),"created_at":"t"}]})
    data=LearnerOwnDataSection(db).export(USER)
    assert data["video_words"]==[{"library_item_id":str(ITEM),"concept_id":cid,"created_at":"t"}]
    query=next((cols,filters) for table,cols,filters in db.queries if table=="learner_video_words")
    assert query[1]=={"user_id":uid} and all(word not in query[0] for word in ["audio","transcript","quote"])


def test_repository_checks_video_ownership_before_reading_links_and_writes_an_idempotent_key():
    client=Mock();library=Mock();links=Mock()
    client.schema.return_value.table.side_effect=lambda name:library if name=="learner_videos" else links
    library.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data=[]
    repo=VideoWordRepository(client)
    assert repo.for_video(USER,ITEM) is None
    links.select.assert_not_called()
    cid=uuid4();repo.add(USER,ITEM,cid)
    assert links.upsert.call_args.args[0]=={"user_id":str(USER),"library_item_id":str(ITEM),"concept_id":str(cid)}
    assert links.upsert.call_args.kwargs=={"on_conflict":"user_id,library_item_id,concept_id","ignore_duplicates":True}


def test_migration_enforces_both_video_and_saved_word_ownership_and_cascades_private_cleanup():
    path=Path(__file__).resolve().parents[2]/"supabase/migrations/20261027070826_video_learning_words_l3.sql"
    sql=path.read_text(encoding="utf-8").lower()
    assert "foreign key (library_item_id, user_id) references v3.learner_videos(id, user_id) on delete cascade" in sql
    assert "foreign key (user_id, concept_id) references v3.saved_concepts(user_id, concept_id) on delete cascade" in sql
    assert "enable row level security" in sql and "from public, anon, authenticated" in sql
    assert "for select to authenticated using ((select auth.uid()) = user_id)" in sql
    assert all(text not in sql for text in ["audio", "transcript", "quote", "alter table v3.saved_concepts"])


def test_video_scoping_loads_concept_details_only_for_linked_words():
    words,resolved=service();words.video_words=Links()
    words.save(me(),SaveFromOccurrence(source="occurrence",library_item_id=ITEM,learning_object_id=uuid4()))
    unrelated=uuid4();words.saved.rows[unrelated]={"concept_id":unrelated,"save_source":"manual"}
    words.concepts.list_by_ids=Mock(return_value=[resolved])
    words.list(me(),"en",ITEM)
    assert words.concepts.list_by_ids.call_args.args[0]==[resolved.id]
