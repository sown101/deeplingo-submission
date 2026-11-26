"""SlidingWindowLimiter with both storages: this process's memory, and Redis over `tests/fake_redis.py` (no server).

With Redis every API process shares the counts; if Redis cannot be reached the limiter fails open to this
process's own counts (requests stay limited per process instead of all being refused).
"""
import logging
import threading

import pytest

from app.platform.rate_limit import RedisWindowStore, SlidingWindowLimiter
from tests.fake_redis import FakeRedis


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def limiter(kind, limits, clock, fake=None):
    if kind == "memory":
        return SlidingWindowLimiter(limits, clock=clock)
    return SlidingWindowLimiter(limits, clock=clock, store=RedisWindowStore(fake or FakeRedis(clock=clock)))


STORES = ["memory", "redis"]


@pytest.mark.parametrize("kind", STORES)
def test_the_window_counts_per_subject_and_action_and_slides(kind):
    clock = Clock()
    limited = limiter(kind, {"turn": (2, 10.0), "start": (1, 10.0)}, clock)
    assert limited.allow("a", "turn") and limited.allow("a", "turn")
    assert not limited.allow("a", "turn")
    assert limited.allow("b", "turn") and limited.allow("a", "start")
    clock.now += 10
    assert limited.allow("a", "turn")


@pytest.mark.parametrize("kind", STORES)
def test_a_refused_request_is_not_counted(kind):
    clock = Clock()
    limited = limiter(kind, {"turn": (2, 10.0)}, clock)
    assert limited.allow("a", "turn")
    clock.now += 1
    assert limited.allow("a", "turn")
    clock.now += 1
    assert not limited.allow("a", "turn")
    clock.now = 1_010.5  # the first request left the window; the refused one never entered it
    assert limited.allow("a", "turn")


def test_two_api_processes_share_the_counts_through_redis():
    clock = Clock()
    fake = FakeRedis(clock=clock)
    first, second = (limiter("redis", {"turn": (3, 60.0)}, clock, fake) for _ in range(2))
    assert first.allow("a", "turn") and second.allow("a", "turn") and first.allow("a", "turn")
    assert not second.allow("a", "turn")
    assert all(key.startswith("deeplingo:ratelimit:turn:") for key in fake.data)


@pytest.mark.parametrize("kind", STORES)
def test_concurrent_requests_never_pass_the_limit(kind):
    clock = Clock()
    fake = FakeRedis(clock=clock)
    limiters = [limiter(kind, {"turn": (10, 60.0)}, clock, fake) for _ in range(1 if kind == "memory" else 3)]
    barrier, allowed = threading.Barrier(30), []

    def hit(index):
        barrier.wait()
        allowed.append(limiters[index % len(limiters)].allow("a", "turn"))

    threads = [threading.Thread(target=hit, args=(index,)) for index in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert allowed.count(True) == 10


def test_an_unreachable_redis_fails_open_to_this_process_counts(caplog):
    clock = Clock()
    fake = FakeRedis(clock=clock)
    limited = limiter("redis", {"turn": (2, 60.0)}, clock, fake)
    fake.down = True
    with caplog.at_level(logging.WARNING):
        results = [limited.allow("learner-1", "turn") for _ in range(3)]
    assert results == [True, True, False]  # still limited, by this process
    assert "rate limit store unavailable" in caplog.text and "learner-1" not in caplog.text
