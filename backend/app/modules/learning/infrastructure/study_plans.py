"""Persistence for daily study plans. Service-role access with an explicit learner
filter on every query; RLS additionally limits direct reads to the owner. A plan and its
proposals are created together by `v3.create_companion_plan`."""
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.learning.application.study_plan import StoredPlan, StoredPlanItem
from app.modules.learning.domain.study_plan import PlanItemDraft, PlanItemKind, PlanItemStatus
from app.platform.persistence import V3Repository

_ITEM_COLUMNS = ("id,position,kind,status,minutes,reason,library_item_id,video_title,companion_entry,"
                 "item_count")


def _item(row: dict, plan_day: date) -> StoredPlanItem:
    return StoredPlanItem(
        id=UUID(row["id"]), plan_day=plan_day, position=int(row["position"]), kind=PlanItemKind(row["kind"]),
        status=PlanItemStatus(row["status"]), minutes=int(row["minutes"]), reason=row["reason"],
        library_item_id=UUID(row["library_item_id"]) if row.get("library_item_id") else None,
        video_title=row.get("video_title"), companion_entry=row.get("companion_entry"),
        item_count=row.get("item_count"),
    )


def _draft_payload(item: PlanItemDraft) -> dict:
    return {
        "kind": item.kind.value, "minutes": item.minutes, "reason": item.reason,
        "library_item_id": str(item.library_item_id) if item.library_item_id else None,
        "video_title": item.video_title, "companion_entry": item.companion_entry,
        "item_count": item.item_count,
    }


class StudyPlanRepository(V3Repository):
    table_name = "companion_plans"

    def _proposals(self):
        return self.client.schema(self.schema).table("companion_proposals")

    def get_plan(self, user_id: UUID, *, language_code: str, plan_day: date) -> StoredPlan | None:
        rows = (
            self.table().select(f"id,plan_day,language_code,intro,companion_proposals({_ITEM_COLUMNS})")
            .eq("user_id", str(user_id)).eq("language_code", language_code).eq("plan_day", plan_day.isoformat())
            .limit(1).execute().data or []
        )
        if not rows:
            return None
        row = rows[0]
        day = date.fromisoformat(row["plan_day"])
        items = sorted((_item(item, day) for item in row.get("companion_proposals") or []),
                       key=lambda item: item.position)
        return StoredPlan(id=UUID(row["id"]), plan_day=day, language_code=row["language_code"],
                          intro=row["intro"], items=tuple(items))

    def create_plan(self, user_id: UUID, *, language_code: str, plan_day: date, intro: str, text_source: str,
                    model: str | None, prompt_version: str | None, items: list[PlanItemDraft]) -> UUID:
        result = self.client.schema(self.schema).rpc("create_companion_plan", {
            "p_user_id": str(user_id), "p_language_code": language_code, "p_plan_day": plan_day.isoformat(),
            "p_intro": intro, "p_text_source": text_source, "p_model": model, "p_prompt_version": prompt_version,
            "p_items": [_draft_payload(item) for item in items],
        }).execute()
        value = result.data[0] if isinstance(result.data, list) and result.data else result.data
        if not isinstance(value, str):
            raise RuntimeError("Study plan creation returned no plan id")
        return UUID(value)

    def append_items(self, user_id: UUID, plan_id: UUID, items: list[PlanItemDraft]) -> list[UUID]:
        result = self.client.schema(self.schema).rpc("append_companion_proposals", {
            "p_user_id": str(user_id), "p_plan_id": str(plan_id),
            "p_items": [_draft_payload(item) for item in items],
        }).execute()
        rows = result.data if isinstance(result.data, list) else ([result.data] if result.data else [])
        return [UUID(row if isinstance(row, str) else next(iter(row.values()))) for row in rows]

    def get_item(self, user_id: UUID, item_id: UUID) -> StoredPlanItem | None:
        rows = (
            self._proposals().select(f"{_ITEM_COLUMNS},companion_plans(plan_day)")
            .eq("id", str(item_id)).eq("user_id", str(user_id)).limit(1).execute().data or []
        )
        if not rows:
            return None
        plan = rows[0].get("companion_plans") or {}
        return _item(rows[0], date.fromisoformat(plan["plan_day"]))

    def decide(self, user_id: UUID, item_id: UUID, *, status: PlanItemStatus) -> bool:
        rows = (
            self._proposals().update({"status": status.value, "decided_at": datetime.now(UTC).isoformat()})
            .eq("id", str(item_id)).eq("user_id", str(user_id)).eq("status", PlanItemStatus.OPEN.value)
            .execute().data or []
        )
        return bool(rows)

    def reopen(self, user_id: UUID, item_id: UUID) -> bool:
        """Back to open from dismissed (the undo of a removal); False when the item was not dismissed."""
        rows = (
            self._proposals().update({"status": PlanItemStatus.OPEN.value, "decided_at": None})
            .eq("id", str(item_id)).eq("user_id", str(user_id)).eq("status", PlanItemStatus.DISMISSED.value)
            .execute().data or []
        )
        return bool(rows)
