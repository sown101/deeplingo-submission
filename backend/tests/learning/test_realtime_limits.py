"""The voice limits (RealtimeGate) with both storages: this process's memory, and Redis over `tests/fake_redis.py`.

No Redis server is used. With Redis a restart keeps the day's seconds, two API processes share the counts, and an
unreachable Redis refuses new sessions (fail closed).
"""
import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.learning.application.agent.voice import MemoryGateStore, RealtimeGate, RealtimeGateUnavailable
from app.modules.learning.domain.realtime import RealtimeLimits
from app.modules.learning.infrastructure.agent_state import RedisGateStore
from tests.fake_redis import FakeRedis
from tests.learning.test_realtime_companion import FakeChannel, auth, run, service, start

OWNER, OTHER = "owner", "other"  # opaque learner ids are enough for the gate
DAY = datetime(2026, 10, 17, 9, tzinfo=UTC)


class Clock:
    def __init__(self, now=DAY):
        self.now = now

    def __call__(self):
        return self.now


def gate(kind, limits, clock, fake=None):
    store = MemoryGateStore() if kind == "memory" else RedisGateStore(fake or FakeRedis(clock=lambda: clock().timestamp()))
    return RealtimeGate(limits, clock=clock, store=store)


STORES = ["memory", "redis"]


@pytest.mark.parametrize("kind", STORES)
def test_concurrency_and_daily_seconds_are_the_same_with_both_stores(kind):
    limits = RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=900, max_concurrent_sessions=1)
    limited = gate(kind, limits, Clock())
    assert limited.acquire(OWNER) == 600
    assert limited.acquire(OWNER) is None  # one session at a time
    limited.release(OWNER, 600)
    assert limited.acquire(OWNER) == 300  # what is left today
    limited.release(OWNER, 290)
    assert limited.acquire(OWNER) is None  # under 30 s left
    together = gate(kind, RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=60,
                                         max_concurrent_sessions=3), Clock())
    assert together.acquire(OWNER) == 60 and together.acquire(OWNER) is None
    together.release(OWNER, 19.2)  # rounded up to whole seconds
    assert together.acquire(OWNER) == 40


@pytest.mark.parametrize("kind", STORES)
def test_two_sessions_of_one_learner_closing_out_of_order_each_give_back_their_own_grant(kind):
    clock = Clock()
    limits = RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=1000, max_concurrent_sessions=2)
    shared = gate(kind, limits, clock)
    first, second = shared.acquire(OWNER), shared.acquire(OWNER)
    assert (first, second) == (600, 400)
    counted = lambda: shared.store.add_seconds(OWNER, DAY.date(), 0)  # noqa: E731
    assert counted() == 1000
    shared.release(OWNER, 100, second)  # the later session ends first
    assert counted() == 700  # 600 for the first still held + 100 really used by the second
    # Its slot is the one that was freed: a new session fits again, the first one's slot is still taken.
    assert shared.acquire(OWNER) is not None and shared.acquire(OWNER) is None


def test_with_redis_a_restart_keeps_the_days_seconds_and_two_processes_share_the_counts():
    clock = Clock()
    fake = FakeRedis(clock=lambda: clock().timestamp())
    limits = RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=900, max_concurrent_sessions=2)
    first = gate("redis", limits, clock, fake)
    assert first.acquire(OWNER) == 600
    first.release(OWNER, 600)
    restarted = gate("redis", limits, clock, fake)  # the API process restarted
    assert restarted.acquire(OWNER) == 300
    second_process = gate("redis", limits, clock, fake)
    assert second_process.acquire(OWNER) is None  # the first process's running session holds the rest
    assert second_process.acquire(OTHER) == 600  # the second of two slots, for someone else
    assert restarted.acquire("third") is None  # both slots are held, whichever process holds them
    clock.now = DAY + timedelta(days=1)
    restarted.release(OWNER, 0)  # a session that ends after midnight is counted on the day it started
    assert restarted.acquire(OWNER) == 600  # a new UTC day


@pytest.mark.parametrize("kind", STORES)
def test_sessions_opened_at_the_same_moment_never_spend_more_than_the_daily_allowance(kind):
    limits = RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=900, max_concurrent_sessions=50)
    gates = [gate(kind, limits, Clock())] if kind == "memory" else None
    if kind == "redis":
        fake = FakeRedis(clock=lambda: DAY.timestamp())
        gates = [gate("redis", limits, Clock(), fake) for _ in range(4)]  # four API processes
    barrier, granted = threading.Barrier(20), []

    def open_one(index):
        barrier.wait()
        granted.append(gates[index % len(gates)].acquire(OWNER))

    threads = [threading.Thread(target=open_one, args=(index,)) for index in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    grants = [seconds for seconds in granted if seconds is not None]
    assert grants and sum(grants) <= 900


def test_an_unreachable_redis_refuses_a_new_voice_session_instead_of_granting_it():
    clock = Clock()
    fake = FakeRedis(clock=lambda: clock().timestamp())
    limited = gate("redis", RealtimeLimits(), clock, fake)
    fake.down = True
    with pytest.raises(RealtimeGateUnavailable):
        limited.acquire(OWNER)
    relay = service()
    relay.gate = limited
    channel = FakeChannel([auth(), start()])
    run(relay.run(channel))
    assert channel.closed == 1011 and channel.json[-1]["code"] == "realtime_unavailable"
    assert relay.voice.opened == []


def test_a_failure_at_the_end_of_a_session_keeps_its_grant_counted():
    clock = Clock()
    fake = FakeRedis(clock=lambda: clock().timestamp())
    limits = RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=900, max_concurrent_sessions=1)
    limited = gate("redis", limits, clock, fake)
    assert limited.acquire(OWNER) == 600
    fake.down = True
    limited.release(OWNER, 10)  # no error for the learner who is leaving
    fake.down = False
    clock.now += timedelta(seconds=600 + 121)  # the slot of that session frees itself
    assert limited.acquire(OWNER) == 300  # its whole grant stayed counted (fail closed)


@pytest.mark.parametrize("kind", STORES)
def test_a_slot_of_a_session_that_never_ended_frees_itself(kind):
    clock = Clock()
    limits = RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=1800, max_concurrent_sessions=1)
    limited = gate(kind, limits, clock)
    assert limited.acquire(OWNER) == 600  # its process died: no release
    assert limited.acquire(OTHER) is None
    clock.now += timedelta(seconds=600 + 121)
    assert limited.acquire(OTHER) == 600
