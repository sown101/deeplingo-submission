"""Whole conversations with simulated learners against the configured real model, with a hard spend cap.

Usage (from backend/, with the backend settings file of the environment to use):
    python scripts/agent/eval_dialogues.py [--cap-usd 3] [--turns 4] [--only id,id] [--scripted-learner]

Each persona (app/modules/learning/application/agent/dialogues.py) talks with the real text channel with in-memory
learner data (no database, no learner data). A model plays the learner from the persona's description (or, with
--scripted-learner, the persona's fixed lines), and one more call judges the whole conversation 1-5 on level fit,
naturalness and helpfulness. The pass mark is the rules (score_dialogue), not the judge. Tokens are counted from the
provider's usage and priced with deliberately high defaults, so the estimate is an upper bound; the run stops before
the next persona once it reaches the cap. Keys and conversation text are never logged; the conversation is printed
to this terminal only.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

os.environ["AI_USAGE_LEDGER_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_live import Meter  # noqa: E402

from app.modules.learning.application.agent.dialogues import PERSONAS, Persona, run_dialogue, scripted  # noqa: E402
from app.platform.config import settings  # noqa: E402
from app.platform.llm import openai_compatible  # noqa: E402

PER_PERSONA_GUARD_USD = 0.25


class _Line(BaseModel):
    say: str = Field(min_length=1, max_length=300)


class _Judgement(BaseModel):
    level_fit: int = Field(ge=1, le=5)
    naturalness: int = Field(ge=1, le=5)
    helpfulness: int = Field(ge=1, le=5)
    note: str = Field(default="", max_length=400)


def model_learner(model):
    def next_line(persona: Persona, turns: list[dict]) -> str:
        if not turns:
            return persona.script[0]
        history = "\n".join(f"Tutor: {turn['reply']}\nYou: {turn['said']}" for turn in turns)
        line = model.generate_structured(
            f"Conversation so far:\n{history}\nTutor: (waiting)\nYour next line:", _Line,
            system_prompt=(f"You play a language learner. {persona.description} Language: {persona.language}, level "
                           f"{persona.level}. Answer the tutor's last message in one short turn, as this learner "
                           "would, mistakes included. Never mention that you are an AI."),
            temperature=0.7, max_tokens=120)
        return line.say
    return next_line


def judge(model, persona: Persona, turns: list[dict]) -> _Judgement | None:
    if not turns:
        return None
    transcript = "\n".join(f"Learner: {turn['said']}\nTutor: {turn['reply']}" for turn in turns)
    return model.generate_structured(
        f"Learner level: {persona.level} ({persona.language}).\n{transcript}", _Judgement,
        system_prompt=("Rate this tutor's replies 1-5: level_fit (right difficulty for the level), naturalness, "
                       "helpfulness (help when stuck, keeps the learner talking). Short note."),
        temperature=0.0, max_tokens=200)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cap-usd", type=float, default=3.0)
    parser.add_argument("--input-price", type=float, default=0.5, help="USD per million input tokens")
    parser.add_argument("--output-price", type=float, default=3.0, help="USD per million output tokens")
    parser.add_argument("--turns", type=int, default=4)
    parser.add_argument("--only", default="", help="comma-separated persona ids")
    parser.add_argument("--scripted-learner", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    meter = Meter(args.input_price, args.output_price)
    openai_compatible.record_usage = meter.record
    model_name = settings.COMPANION_MODEL or settings.SPEAKING_COACH_MODEL or settings.AI_MODEL_NAME
    agent = openai_compatible.OpenAICompatibleLLMProvider(model_name=model_name)
    helper = openai_compatible.OpenAICompatibleLLMProvider(model_name=model_name)
    wanted = {item for item in args.only.split(",") if item}
    failures = 0
    for persona in PERSONAS:
        if wanted and persona.id not in wanted:
            continue
        if meter.usd + PER_PERSONA_GUARD_USD > args.cap_usd:
            print(f"stopped before {persona.id}: estimate ${meter.usd:.3f} near the cap ${args.cap_usd:.2f}")
            break
        learner = scripted if args.scripted_learner else model_learner(helper)
        turns = min(args.turns, len(persona.script)) if args.scripted_learner else args.turns
        result = run_dialogue(agent, persona, learner=learner, turns=turns)
        verdict = judge(helper, persona, result.turns) if result.turns else None
        failures += 0 if result.ok else 1
        failed = [name for name, ok in result.checks.items() if not ok]
        latency = (sorted(result.latency_ms)[len(result.latency_ms) // 2] if result.latency_ms else 0)
        print(f"{'PASS' if result.ok else 'FAIL'} {persona.id} median_turn_ms={latency} failed={failed} "
              f"judge={verdict.model_dump() if verdict else None} error={result.error}")
        for turn in result.turns:
            print(f"   learner: {turn['said']}\n   agent:   {turn['reply']}  {turn['shown'] or ''}")
    print(f"estimate ${meter.usd:.3f} ({meter.calls} calls)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
