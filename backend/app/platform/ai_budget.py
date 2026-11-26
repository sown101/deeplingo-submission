"""A daily cap on paid AI spend for the whole system (owner, 2026-11-18: "decide it from the sources").

The counter reserves estimated cost before a paid call and reconciles it when usage is known. Redis shares the
counter across workers. A failed shared reservation refuses admission; local development can use a local counter.

Prices are list prices in USD (Google AI Studio pricing page, 2026-11-18; Azure Speech real-time recognition
plus pronunciation assessment as reported by Microsoft Q&A and third parties, the official page showing no
figure). They are estimates for a guard, not a bill: the text proxy may charge differently. A model missing
from the table is priced as an expensive one, so an unknown model reaches the cap sooner, never later.
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

logger = logging.getLogger(__name__)

# USD per million tokens: (input, output including thinking).
TEXT_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-live": (0.75, 4.50),
}
UNKNOWN_TEXT_PRICE = (1.25, 10.00)
LIVE_AUDIO_IN_PER_MINUTE = 0.005
LIVE_AUDIO_OUT_PER_MINUTE = 0.018
AZURE_SPEECH_PER_HOUR = 1.30  # real-time recognition 1.00 + pronunciation assessment 0.30
AZURE_TTS_PER_MILLION_CHARACTERS = 15.0  # neural voices, list price
MICRO = 1_000_000  # the counter holds micro-dollars
_RETENTION_SECONDS = 3 * 24 * 3600
_RESERVE_SCRIPT = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
if used + amount > tonumber(ARGV[2]) then return 0 end
redis.call('INCRBY', KEYS[1], amount)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""


def text_cost(model: str, prompt_tokens: int, output_tokens: int) -> float:
    price_in, price_out = TEXT_PRICES.get(model, UNKNOWN_TEXT_PRICE)
    return (max(0, prompt_tokens) * price_in + max(0, output_tokens) * price_out) / 1_000_000


def live_cost(audio_in_seconds: float, audio_out_seconds: float) -> float:
    return (max(0.0, audio_in_seconds) * LIVE_AUDIO_IN_PER_MINUTE
            + max(0.0, audio_out_seconds) * LIVE_AUDIO_OUT_PER_MINUTE) / 60


def speech_cost(seconds: float) -> float:
    return max(0.0, seconds) * AZURE_SPEECH_PER_HOUR / 3600


def tts_cost(characters: int) -> float:
    return max(0, characters) * AZURE_TTS_PER_MILLION_CHARACTERS / 1_000_000


@dataclass(frozen=True)
class SpendReservation:
    key: str
    amount: int


class DailyBudget:
    def __init__(self, *, cap_usd: float, redis=None, require_redis: bool = False,
                 today=lambda: datetime.now(UTC).date()):
        self.cap_usd, self.redis, self.today = cap_usd, redis, today
        self.require_redis = require_redis
        self._local: dict[str, int] = {}
        self._lock = threading.Lock()

    def _key(self) -> str:
        return f"ai:spend:{self.today().isoformat()}"

    def spent(self) -> float:
        key = self._key()
        if self.redis is not None:
            try:
                return int(self.redis.get(key) or 0) / MICRO
            except Exception as exc:
                logger.warning("ai budget read failed error=%s", type(exc).__name__)
                return math.inf
        if self.require_redis:
            return math.inf
        with self._lock:
            return self._local.get(key, 0) / MICRO

    def allows(self) -> bool:
        """False once today's spend reached the cap; a cap of 0 turns the guard off."""
        return self.cap_usd <= 0 or self.spent() < self.cap_usd

    def reserve(self, usd: float) -> SpendReservation | None:
        key = self._key()
        if self.cap_usd <= 0:
            return SpendReservation(key, 0)
        amount = max(1, math.ceil(usd * MICRO))
        cap = round(self.cap_usd * MICRO)
        if self.redis is not None:
            try:
                accepted = self.redis.eval(_RESERVE_SCRIPT, 1, key, amount, cap, _RETENTION_SECONDS)
            except Exception as exc:
                logger.warning("ai budget reservation failed error=%s", type(exc).__name__)
                return None
            return SpendReservation(key, amount) if accepted else None
        if self.require_redis:
            return None
        with self._lock:
            used = self._local.get(key, 0)
            if used + amount > cap:
                return None
            self._local = {key: used + amount}
        return SpendReservation(key, amount)

    def charge(self, usd: float, *, reservation: SpendReservation | None = None) -> None:
        amount = round(max(0.0, usd) * MICRO) - (reservation.amount if reservation else 0)
        if amount == 0:
            return
        key = reservation.key if reservation else self._key()
        if self.redis is not None:
            try:
                self.redis.incrby(key, amount)
                self.redis.expire(key, _RETENTION_SECONDS)
            except Exception as exc:
                logger.warning("ai budget write failed error=%s", type(exc).__name__)
            return
        if self.require_redis or key != self._key():
            return
        with self._lock:
            self._local = {key: self._local.get(key, 0) + amount}


@lru_cache(maxsize=1)
def daily_budget() -> DailyBudget:
    from app.platform.config import settings
    redis = None
    if settings.REDIS_URL:
        try:
            import redis as redis_lib
            redis = redis_lib.Redis.from_url(settings.REDIS_URL, socket_timeout=0.5, socket_connect_timeout=0.5)
        except Exception as exc:
            logger.warning("ai budget redis unavailable error=%s", type(exc).__name__)
    shared = bool(settings.REDIS_URL) or settings.ENVIRONMENT in {"staging", "production"}
    return DailyBudget(cap_usd=settings.AI_DAILY_BUDGET_USD, redis=redis, require_redis=shared)
