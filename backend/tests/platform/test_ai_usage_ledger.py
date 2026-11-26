"""AI cost ledger (2026-11-05): token counts per call, no learner data, never blocking. No live AI or DB."""
from types import SimpleNamespace

from app.platform.llm import ledger
from app.platform.llm.openai_compatible import _log_usage


def test_a_row_keeps_only_the_scope_kind_and_token_counts():
    row = ledger.usage_row(provider="gemini", model="gemini-3.5-flash-lite", response_model="PartsAnswer",
                           scope="region_preparation:9b0c-learner-linked-id", prompt_tokens=3100,
                           completion_tokens=120, reasoning_tokens=None)
    assert row["feature"] == "region_preparation" and "9b0c" not in str(row)
    assert (row["prompt_tokens"], row["completion_tokens"], row["reasoning_tokens"]) == (3100, 120, 0)
    assert set(row) == {"occurred_at", "provider", "model", "response_model", "feature",
                        "prompt_tokens", "completion_tokens", "reasoning_tokens"}


def test_every_logged_model_call_is_recorded(monkeypatch):
    rows = []
    monkeypatch.setattr("app.platform.llm.openai_compatible.record_usage", lambda **fields: rows.append(fields))
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, completion_tokens_details=None))
    _log_usage(response, provider=SimpleNamespace(provider_name="gemini", model_name="m"),
               response_model=SimpleNamespace(__name__="PartsAnswer"))
    assert rows and rows[0]["prompt_tokens"] == 10 and rows[0]["response_model"] == "PartsAnswer"


def test_a_disabled_ledger_queues_nothing(monkeypatch):
    monkeypatch.setattr("app.platform.config.settings.AI_USAGE_LEDGER_ENABLED", False)
    before = ledger._QUEUE.qsize()
    ledger.record_usage(provider="p", model="m", response_model="R", scope="none", prompt_tokens=1,
                        completion_tokens=1, reasoning_tokens=0)
    assert ledger._QUEUE.qsize() == before


def test_the_report_prices_tokens_per_feature_and_model():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ai_cost_report", Path(__file__).parents[2] / "scripts" / "ai_cost_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    rows = [{"feature": "transcript_parts", "model": "m", "prompt_tokens": 1_000_000, "completion_tokens": 500_000,
             "reasoning_tokens": 500_000}, {"feature": "lookup", "model": "unpriced", "prompt_tokens": 5,
                                             "completion_tokens": 1, "reasoning_tokens": 0}]
    lines, grand = report.summarize(rows, {"m": {"input": 0.10, "output": 0.40}})
    assert abs(grand - 0.50) < 1e-9 and any("usd=?" in line for line in lines)
