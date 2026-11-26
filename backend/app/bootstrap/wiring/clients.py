import time
from functools import lru_cache

from fastapi import HTTPException, status
from redis import Redis

from app.platform.config import settings
from app.platform.rate_limit import RedisWindowStore, SlidingWindowLimiter
from app.platform.supabase import supabase_service


def service_client():
    """Service-role Supabase client for request-scoped wiring, or 503 when unconfigured."""
    if not supabase_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase service client is not configured",
        )
    return supabase_service


@lru_cache(maxsize=4)
def redis_client(url: str) -> Redis:
    """One pooled client per Redis URL. It connects on first use; short timeouts keep a request from hanging."""
    return Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


def request_limiter(limits: dict[str, tuple[int, float]]) -> SlidingWindowLimiter:
    """Shared counts in the Redis of `REDIS_URL` when it is set (every API process, kept across restarts), else this
    process's memory. Callers cache the limiter."""
    if not settings.REDIS_URL:
        return SlidingWindowLimiter(limits)
    return SlidingWindowLimiter(limits, clock=time.time, store=RedisWindowStore(redis_client(settings.REDIS_URL)))
