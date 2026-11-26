"""AI cost report from the ledger (v3.ai_usage_events), per feature and model.

    python scripts/ai_cost_report.py --days 7 --prices prices.json

prices.json maps a model to its USD price per million tokens, for example
{"gemini-3.5-flash-lite": {"input": 0.10, "output": 0.40}}. Check the provider's current price list;
without a price the report shows tokens only. Reasoning tokens are billed as output. Read only.
Gemini Live audio and Azure Speech are not in this ledger.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta


def summarize(rows, prices):
    totals = defaultdict(lambda: [0, 0, 0, 0])
    for row in rows:
        key = (row["feature"], row["model"])
        totals[key][0] += 1
        totals[key][1] += row["prompt_tokens"]
        totals[key][2] += row["completion_tokens"] + row.get("reasoning_tokens", 0)
    lines, grand = [], 0.0
    for (feature, model), (calls, inp, out) in sorted(((k, v[:3]) for k, v in totals.items()), key=lambda i: -i[1][1]):
        price = prices.get(model)
        cost = (inp * price["input"] + out * price["output"]) / 1_000_000 if price else None
        grand += cost or 0.0
        lines.append(f"{feature:28} {model:28} calls={calls:6} in={inp:10} out={out:9} "
                     + (f"usd={cost:.4f}" if cost is not None else "usd=?"))
    return lines, grand


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--prices", default="")
    args = parser.parse_args()
    prices = json.load(open(args.prices, encoding="utf-8")) if args.prices else {}
    from app.platform.supabase import supabase_service
    since = (datetime.now(UTC) - timedelta(days=args.days)).isoformat()
    rows, offset = [], 0
    while True:
        page = (supabase_service.schema("v3").table("ai_usage_events")
                .select("feature,model,prompt_tokens,completion_tokens,reasoning_tokens")
                .gte("occurred_at", since).range(offset, offset + 999).execute().data or [])
        rows += page
        if len(page) < 1000:
            break
        offset += 1000
    lines, grand = summarize(rows, prices)
    print(f"AI usage, last {args.days} days: {len(rows)} calls")
    print("\n".join(lines))
    print(f"TOTAL usd={grand:.4f} (priced models only)")


if __name__ == "__main__":
    main()
