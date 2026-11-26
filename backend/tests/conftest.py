"""Tests never reach a shared service through the local `.env`: no AI usage rows are written to the real ledger
(2026-11-17 a local run left `test-model` rows on development) and the AI budget counts in memory only."""
import pytest

from app.platform import ai_budget
from app.platform.config import settings


@pytest.fixture(autouse=True)
def _no_shared_ai_state(monkeypatch):
    monkeypatch.setattr(settings, "AI_USAGE_LEDGER_ENABLED", False)
    monkeypatch.setattr(settings, "REDIS_URL", "")
    ai_budget.daily_budget.cache_clear()
    yield
    getattr(ai_budget.daily_budget, "cache_clear", lambda: None)()
