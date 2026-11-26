"""Run the agent's fixed eval scenarios against the configured real model, with a hard spend cap.

Usage (from backend/, with the backend settings file of the environment to use):
    python scripts/agent/eval_live.py [--cap-usd 2] [--input-price 0.5] [--output-price 3.0] [--only id,id]

Each scenario goes through the real text channel with in-memory learner data (app/modules/learning/application/
agent/evals.py): no database, no learner data. Tokens are counted from the provider's usage of every call and
priced with the given USD per million tokens (defaults are deliberately high, so the estimate is an upper
bound); the run stops before the next scenario once the estimate reaches the cap. The AI cost ledger is switched
off for this process. Keys are never printed.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ["AI_USAGE_LEDGER_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.modules.learning.application.agent.evals import SCENARIOS, run_scenario  # noqa: E402
from app.platform.config import settings  # noqa: E402
from app.platform.llm import openai_compatible  # noqa: E402

PER_SCENARIO_GUARD_USD = 0.10  # never start a scenario that could pass the cap by more than this


class Meter:
    def __init__(self, input_price: float, output_price: float):
        self.input_price, self.output_price = input_price, output_price
        self.prompt_tokens = self.completion_tokens = self.calls = 0

    def record(self, **fields) -> None:
        self.calls += 1
        self.prompt_tokens += fields.get("prompt_tokens") or 0
        self.completion_tokens += (fields.get("completion_tokens") or 0) + (fields.get("reasoning_tokens") or 0)

    @property
    def usd(self) -> float:
        return (self.prompt_tokens * self.input_price + self.completion_tokens * self.output_price) / 1_000_000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cap-usd", type=float, default=2.0)
    parser.add_argument("--input-price", type=float, default=0.5, help="USD per million input tokens")
    parser.add_argument("--output-price", type=float, default=3.0, help="USD per million output tokens")
    parser.add_argument("--only", default="", help="comma-separated scenario ids")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    meter = Meter(args.input_price, args.output_price)
    openai_compatible.record_usage = meter.record  # count every billed call (the ledger stays off)
    model_name = settings.COMPANION_MODEL or settings.SPEAKING_COACH_MODEL or settings.AI_MODEL_NAME
    try:
        model = openai_compatible.OpenAICompatibleLLMProvider(model_name=model_name)
    except Exception as exc:
        print(f"provider not configured: {type(exc).__name__}")
        return 2
    print(f"model={model.model_name} provider={settings.AI_PROVIDER} cap_usd={args.cap_usd}")

    wanted = {item.strip() for item in args.only.split(",") if item.strip()}
    results = []
    for scenario in SCENARIOS:
        if wanted and scenario.id not in wanted:
            continue
        if meter.usd + PER_SCENARIO_GUARD_USD > args.cap_usd:
            print(f"stopped before {scenario.id}: estimated spend {meter.usd:.4f} USD is near the cap")
            break
        result = run_scenario(model, scenario, live=True)
        results.append(result)
        failed = [name for name, passed in result.checks.items() if not passed]
        print(f"{scenario.id:14} {'PASS' if result.ok else 'FAIL'} latency_ms={result.latency_ms} "
              f"shown={','.join(result.shown) or '-'} tools={','.join(result.tools) or '-'}"
              f"{' failed=' + ','.join(failed) if failed else ''}{' error=' + result.error if result.error else ''}"
              f" running_usd={meter.usd:.4f}")
        if result.reply:
            print(f"{'':14} reply: {result.reply[:160]}")
    passed = sum(result.ok for result in results)
    print(f"passed {passed}/{len(results)} calls={meter.calls} prompt_tokens={meter.prompt_tokens} "
          f"completion_tokens={meter.completion_tokens} estimated_usd={meter.usd:.4f}")
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
