"""No hosted infrastructure: isolated producer bounds and durable admission."""
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
import socket
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.bootstrap.worker import celery_app
from app.platform.config import Settings, settings
from app.modules.content.domain.work_intents import VideoWorkIntent
from app.modules.content.worker.dispatch import ContentWorkDispatcher, _publish
from app.modules.content.worker import tasks as worker


@pytest.mark.parametrize('stage,task_name',[
    ('transcript','process_prepared_video_v3'),('learning_preparation','prepare_video_learning_content')])
def test_producer_connection_is_isolated_bounded_and_no_retry(monkeypatch,stage,task_name):
    original_options=dict(celery_app.conf.broker_transport_options)
    observed={};connection=object()
    @contextmanager
    def factory(**kwargs):
        observed['options']=kwargs
        yield connection
        observed['closed']=True
    def publish(**kwargs):observed['publish']=kwargs;return SimpleNamespace(id='receipt')
    monkeypatch.setattr(celery_app,'connection_for_write',factory)
    monkeypatch.setattr(getattr(worker,task_name),'apply_async',publish)
    intent=VideoWorkIntent(uuid4(),uuid4(),stage,1,'pending')
    assert _publish(intent)=='receipt'
    assert observed['publish']=={'args':[str(intent.id)],'connection':connection,'retry':False}
    options=observed['options']['transport_options']
    assert options['socket_timeout']==settings.CONTENT_PUBLISH_SOCKET_TIMEOUT_SECONDS
    assert options['socket_connect_timeout']==settings.CONTENT_PUBLISH_CONNECT_TIMEOUT_SECONDS
    assert options['max_retries']==0 and options['retry_on_timeout'] is False
    assert observed['closed'] and celery_app.conf.broker_transport_options==original_options
    assert celery_app.conf.worker_concurrency==2 and celery_app.conf.worker_prefetch_multiplier==1


@pytest.mark.parametrize('field',[
    'CONTENT_PUBLISH_CONNECT_TIMEOUT_SECONDS','CONTENT_PUBLISH_SOCKET_TIMEOUT_SECONDS'])
@pytest.mark.parametrize('value',[0,-1,11,float('inf'),float('nan')])
def test_producer_io_bounds_reject_unbounded_values(field,value):
    with pytest.raises(ValidationError):Settings(_env_file=None,ENVIRONMENT='test',**{field:value})


def test_broker_blackhole_after_admission_returns_202_without_losing_intent(monkeypatch):
    # This is a deterministic local TCP blackhole, NOT a Redis replacement or
    # qualification of the development broker. No 40-second unit test.
    from tests.content.test_library import make_service, FakeVerifier, USER_A
    from app.bootstrap.wiring.identity import get_jwt_verifier
    from app.bootstrap.wiring.content import get_learner_library_service
    from app.main import app
    service,videos,library,_,_=make_service()
    intents=service.work_intents
    receipts=[]
    monkeypatch.setattr(intents,'get',lambda identity:intents.rows.get(identity),raising=False)
    monkeypatch.setattr(intents,'due',lambda **kwargs:list(intents.rows.values())[:kwargs['limit']],raising=False)
    def acknowledged(identity,*,accepted):
        receipts.append((identity,accepted))
        if accepted:intents.rows[identity]=replace(intents.rows[identity],state='dispatched')
    monkeypatch.setattr(intents,'record_dispatch',acknowledged,raising=False)
    service.dispatcher=ContentWorkDispatcher(intents)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(2);listener.settimeout(.1)
    address=listener.getsockname();stop=threading.Event();connections=[]
    def blackhole():
        while not stop.is_set():
            try:
                connection,_=listener.accept();connections.append(connection)
            except socket.timeout:continue
            except OSError:return
    thread=threading.Thread(target=blackhole,daemon=True);thread.start()
    factory=celery_app.connection_for_write
    monkeypatch.setattr(celery_app,'connection_for_write',lambda **kwargs:factory(
        url=f'redis://127.0.0.1:{address[1]}/0',**kwargs))
    monkeypatch.setattr(settings,'CONTENT_PUBLISH_CONNECT_TIMEOUT_SECONDS',.05)
    monkeypatch.setattr(settings,'CONTENT_PUBLISH_SOCKET_TIMEOUT_SECONDS',.05)
    old_overrides=dict(app.dependency_overrides)
    app.dependency_overrides[get_jwt_verifier]=lambda:FakeVerifier(USER_A)
    app.dependency_overrides[get_learner_library_service]=lambda:service
    try:
        with TestClient(app) as client:
            start=time.monotonic()
            first=client.post('/api/v1/v3/learner/me/library/videos',
                headers={'Authorization':'Bearer test.test.test'},json={'url':'https://youtube.com/watch?v=shared123'})
            assert time.monotonic()-start<2
            assert first.status_code==202 and first.json()['command_status']=='accepted'
            identity=next(iter(intents.rows))
            assert receipts==[(identity,False)] and intents.rows[identity].state=='pending'
            second=client.post('/api/v1/v3/learner/me/library/videos',
                headers={'Authorization':'Bearer test.test.test'},json={'url':'https://youtube.com/watch?v=shared123'})
            assert second.status_code==202 and len(intents.rows)==len(library.rows)==len(videos.by_id)==1
            assert first.json()['item']['library_item_id']==second.json()['item']['library_item_id']
            recovered=ContentWorkDispatcher(intents,publish=lambda row:'restored-receipt')
            assert recovered.reconcile_due(limit=1)==(1,1)
            assert intents.rows[identity].state=='dispatched' and len(intents.rows)==1
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(old_overrides)
        stop.set();listener.close();thread.join(timeout=1)
        for connection in connections:connection.close()
