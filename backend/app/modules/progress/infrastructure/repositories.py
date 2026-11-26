"""Progress reads. Service-role access with the learner named on every call; the database sums the rows
(`v3.learner_progress_totals`), so nothing is paged or capped here."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from app.modules.progress.domain.models import METRICS, ProgressTotals, ScoreDay
from app.platform.persistence import V3Repository


def _int(value) -> int:
    return int(value or 0)


def _day(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def totals_from_json(data: dict | None) -> ProgressTotals:
    data = data or {}
    cards: dict[str, dict[str, int]] = {}
    for row in data.get("cards") or []:
        deck = cards.setdefault(row["language_code"], {})
        deck[row["state"]] = deck.get(row["state"], 0) + _int(row["total"])
        deck["due"] = deck.get("due", 0) + _int(row["due"])
    return ProgressTotals(
        days={_day(row["day"]): _int(row["count"]) for row in data.get("days") or []},
        graded={row["kind"]: (_int(row["attempts"]), _int(row["correct"])) for row in data.get("graded") or []},
        grammar_learned=_int(data.get("grammar_learned")), grammar_correct=_int(data.get("grammar_correct")),
        regions=_int(data.get("regions")),
        speaking_sessions=_int(data.get("speaking_sessions")), speaking_seconds=_int(data.get("speaking_seconds")),
        week_seconds={_day(row["week"]): _int(row["seconds"]) for row in data.get("weeks") or []},
        cards=cards,
        scores={_day(row["day"]): ScoreDay(sessions=_int(row["sessions"]), sums={
            metric: (float(row.get(metric + "_sum") or 0), _int(row.get(metric + "_count"))) for metric in METRICS})
            for row in data.get("scores") or []},
        weak={str(row["word"]): _int(row["count"]) for row in data.get("weak") or []},
        data_languages=tuple(sorted(str(code) for code in data.get("languages") or [])),
    )


class ProgressRepository(V3Repository):
    table_name = "learner_activity_log"

    def totals(self, *, user_id: UUID, language_code: str | None, now: datetime,
               utc_offset_minutes: int) -> ProgressTotals:
        data = self.client.schema(self.schema).rpc("learner_progress_totals", {
            "p_user_id": str(user_id), "p_language_code": language_code, "p_now": now.isoformat(),
            "p_utc_offset_minutes": utc_offset_minutes,
        }).execute().data
        return totals_from_json(data)

    def languages(self, *, user_id: UUID) -> list[str]:
        rows = (self.client.schema(self.schema).table("user_language_preferences").select("language_code")
                .eq("user_id", str(user_id)).order("is_primary", desc=True).limit(50).execute().data or [])
        return list(dict.fromkeys(row["language_code"] for row in rows))
