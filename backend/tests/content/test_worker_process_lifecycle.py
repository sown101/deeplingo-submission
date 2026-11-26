import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.platform.process_clients import ProcessClientCache, ProcessClientProxy


def test_lazy_same_process_reuse_and_shutdown():
    made, closed = [], []
    def factory():
        value = object()
        made.append(value)
        return value
    cache = ProcessClientCache(factory, closed.append)
    assert made == []
    assert cache.get() is cache.get()
    cache.shutdown()
    assert closed == made
    assert cache.get() is not made[0]


def test_parallel_first_access_uses_one_instance():
    made = []
    def factory():
        made.append(object())
        return made[-1]
    cache = ProcessClientCache(factory)
    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(lambda _: cache.get(), range(40)))
    assert len(made) == 1
    assert all(value is made[0] for value in values)


def test_pid_transition_drops_parent_without_vendor_close(monkeypatch):
    made, closed = [], []
    def factory():
        made.append(object())
        return made[-1]
    cache = ProcessClientCache(factory, closed.append)
    parent = cache.get()
    monkeypatch.setattr(os, 'getpid', lambda: 999999)
    assert cache.get() is not parent
    assert cache._pid == 999999
    assert closed == []


def test_alias_resolves_process_cache_on_each_operation(monkeypatch):
    cache = ProcessClientCache(lambda: SimpleNamespace(pid=os.getpid()))
    proxy = ProcessClientProxy(SimpleNamespace(client=None))
    class Owner:
        @property
        def client(self):
            return cache.get()
        def is_connected(self):
            return self.client is not None
    proxy = ProcessClientProxy(Owner())
    assert proxy.pid == os.getpid()
    monkeypatch.setattr(os, 'getpid', lambda: 999998)
    assert proxy.pid == 999998
    assert bool(proxy)


def test_unconfigured_proxy_fails_closed():
    proxy = ProcessClientProxy(SimpleNamespace(client=None, is_connected=lambda: False))
    assert not proxy
    with pytest.raises(RuntimeError, match='not configured'):
        proxy.table('videos')


def test_supabase_import_is_lazy_and_scopes_independent():
    from app.platform import supabase as module
    assert module.supabase_client is not module.supabase_service_client
    assert module.supabase_client._cache is not module.supabase_service_client._cache
    assert isinstance(module.supabase, ProcessClientProxy)
    assert isinstance(module.supabase_service, ProcessClientProxy)


def test_supported_config_and_shutdown_hook():
    from app.bootstrap.worker import celery_app, close_worker_process_clients
    assert celery_app.conf.worker_pool == 'prefork'
    assert celery_app.conf.worker_concurrency == 2
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_time_limit == 1800
    assert celery_app.conf.task_soft_time_limit == 1500
    assert not celery_app.conf.task_acks_late
    close_worker_process_clients()


def _fork_probe(cache, parent, connection):
    value = cache.get()
    connection.send({'pid': os.getpid(), 'owner': cache._pid,
                     'fresh': value is not parent, 'reuse': value is cache.get()})
    connection.close()


@pytest.mark.skipif('fork' not in multiprocessing.get_all_start_methods(), reason='actual fork proof requires Linux')
def test_real_fork_parent_not_reused_two_independent_children():
    cache = ProcessClientCache(object)
    parent = cache.get()
    ctx = multiprocessing.get_context('fork')
    rows = []
    for _ in range(2):
        receiver, sender = ctx.Pipe(False)
        child = ctx.Process(target=_fork_probe, args=(cache, parent, sender))
        # Simulate another parent thread holding the cache mutex at fork.
        cache._lock.acquire()
        try:
            child.start()
        finally:
            cache._lock.release()
        sender.close()
        assert receiver.poll(10)
        rows.append(receiver.recv())
        receiver.close()
        child.join(10)
        assert child.exitcode == 0
    assert rows[0]['pid'] != rows[1]['pid']
    assert all(row['pid'] == row['owner'] and row['fresh'] and row['reuse'] for row in rows)
    assert cache.get() is parent


def test_imported_repository_alias_resolves_new_process(monkeypatch):
    from app.platform.persistence import V3Repository
    class Client:
        def __init__(self):
            self.pid = os.getpid()
        def schema(self, name):
            return self
        def table(self, name):
            return self.pid
    cache = ProcessClientCache(Client)
    class Owner:
        @property
        def client(self):
            return cache.get()
    repository = V3Repository(ProcessClientProxy(Owner()))
    repository.table_name = 'fixture'
    assert repository.table() == os.getpid()
    monkeypatch.setattr(os, 'getpid', lambda: 999997)
    assert repository.table() == 999997


def test_canonical_launcher_excludes_windows(monkeypatch):
    from scripts.content import run_content_worker
    monkeypatch.setattr(run_content_worker.sys, 'platform', 'win32')
    with pytest.raises(SystemExit, match='NOT RELIABILITY QUALIFIED'):
        run_content_worker.main()


def test_optional_native_tokenizer_is_lazy_pid_owned(monkeypatch):
    from app.modules.content.infrastructure import sources as providers
    made = []
    class Engine:
        def __init__(self):
            made.append(os.getpid())
        def romanize(self, text):
            return text
    monkeypatch.setattr(providers, '_CUTLET', ProcessClientCache(Engine))
    assert made == []
    romanizer = providers.LocalRomanizationProvider()
    assert romanizer.romanize('fixture', 'ja') == {'romaji': 'fixture'}
    assert romanizer.romanize('fixture', 'ja') == {'romaji': 'fixture'}
    assert made == [os.getpid()]
    monkeypatch.setattr(os, 'getpid', lambda: 999996)
    romanizer.romanize('fixture', 'ja')
    assert made[-1] == 999996
