"""Content-owned durable delivery identities for the two active V3 stages."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.modules.content.domain.library import LearnerVideo
from app.modules.content.domain.catalog import Video
from app.modules.content.application.store_ports import ContentWorkAdmissionConflict, ContentWorkBackpressure
from app.modules.content.domain.work_claims import ContentClaim
from app.modules.content.domain.work_intents import AdmittedVideoWork, VideoWorkIntent
from app.modules.content.infrastructure.repositories.content_claims import fenced_rpc
from app.platform.persistence import V3Repository


def _row(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) else None


class VideoWorkIntentRepository(V3Repository):
    table_name = "video_work_intents"

    def admit(
        self, *, user_id: UUID, video_id: UUID, action: str,
        library_item_id: UUID | None = None,
    ) -> AdmittedVideoWork:
        try:
            result = self.client.rpc("admit_video_content_work", {
                "p_user_id": str(user_id),
                "p_video_id": str(video_id),
                "p_action": action,
                "p_library_item_id": str(library_item_id) if library_item_id else None,
            }).execute()
        except Exception as exc:
            if str(getattr(exc, "code", "")) == "DL002":
                raise ContentWorkBackpressure("Content admission temporarily unavailable") from exc
            if str(getattr(exc, "code", "")) == "23514":
                raise ContentWorkAdmissionConflict("Content work retry is no longer eligible") from exc
            raise
        data = _row(result.data)
        if data is None:
            raise RuntimeError("Content work admission returned no row")
        return AdmittedVideoWork(
            association=LearnerVideo(**data["association"]),
            video=Video(**data["video"]),
            intent_id=UUID(str(data["intent_id"])) if data.get("intent_id") else None,
            command_status=str(data["command_status"]),
            dispatch_now=bool(data["dispatch_now"]),
        )

    def get(self, intent_id: UUID) -> VideoWorkIntent | None:
        result = self.table().select("id,video_id,stage,generation,state").eq("id", str(intent_id)).limit(1).execute()
        row = _row(result.data)
        return VideoWorkIntent.from_row(row) if row else None

    def active_for_video(self, *, video_id: UUID, stage: str) -> VideoWorkIntent | None:
        result = (
            self.table().select("id,video_id,stage,generation,state")
            .eq("video_id", str(video_id)).eq("stage", stage)
            .in_("state", ["pending", "dispatched", "running"])
            .order("generation", desc=True).limit(1).execute()
        )
        row = _row(result.data)
        return VideoWorkIntent.from_row(row) if row else None

    def due(self, *, limit: int = 50) -> list[VideoWorkIntent]:
        if not 1 <= limit <= 100:
            raise ValueError("Content work scan limit must be 1..100")
        result = (
            self.table().select("id,video_id,stage,generation,state")
            .in_("state", ["pending", "dispatched"])
            .lte("next_dispatch_at", datetime.now(UTC).isoformat())
            .order("next_dispatch_at").order("created_at")
            .limit(limit).execute()
        )
        return [VideoWorkIntent.from_row(row) for row in result.data or []]

    def claim(self, intent_id: UUID, *, preparation_version: str | None = None,
              lease_seconds: int = 2100) -> ContentClaim | None:
        scoped = self.client.schema("v3") if hasattr(self.client, "schema") else self.client
        result = scoped.rpc("claim_leased_content_work", {
            "p_intent_id": str(intent_id),
            "p_preparation_version": preparation_version,
            "p_lease_seconds": lease_seconds,
        }).execute()
        row = _row(result.data)
        if row is None:
            return None
        return ContentClaim(
            intent_id=UUID(row["id"]), video_id=UUID(row["video_id"]),
            stage=row["stage"], generation=row["generation"],
            token=UUID(row["claim_token"]), epoch=row["claim_epoch"],
            lease_expires_at=datetime.fromisoformat(row["lease_expires_at"].replace("Z", "+00:00")),
            region_preparation_id=UUID(row["region_preparation_id"]) if row.get("region_preparation_id") else None,
        )

    def record_dispatch(self, intent_id: UUID, *, accepted: bool) -> None:
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "next_dispatch_at": (now + timedelta(seconds=300 if accepted else 60)).isoformat(),
            "updated_at": now.isoformat(),
        }
        if accepted:
            payload.update({"state": "dispatched", "last_dispatched_at": now.isoformat()})
        (
            self.table().update(payload).eq("id", str(intent_id))
            .in_("state", ["pending", "dispatched"]).execute()
        )

    def complete_transcript(self, claim: ContentClaim) -> tuple[Video, UUID | None]:
        data = _row(fenced_rpc(self.client, "complete_claimed_transcript", claim))
        if data is None:
            raise RuntimeError("Transcript completion returned no row")
        preparation_id = data.get("preparation_intent_id")
        return Video(**data["video"]), UUID(str(preparation_id)) if preparation_id else None

    def finish_preparation(self, claim: ContentClaim, *, status: str, usable_count: int,
                           support_language_code: str | None, failure_code: str | None) -> None:
        fenced_rpc(self.client, "complete_claimed_preparation", claim,
                   p_status=status, p_usable_count=usable_count,
                   p_support_language_code=support_language_code, p_failure_code=failure_code)

    def finish_region_preparation(self, claim: ContentClaim, *, status: str, usable_count: int,
                                  failure_code: str | None) -> None:
        fenced_rpc(self.client, "complete_claimed_region_preparation", claim,
                   p_status=status, p_usable_count=usable_count, p_failure_code=failure_code)

    def recover_expired(self, *, limit: int = 50) -> int:
        if not 1 <= limit <= 100:
            raise ValueError("Content recovery limit must be 1..100")
        scoped = self.client.schema("v3") if hasattr(self.client, "schema") else self.client
        return int(scoped.rpc("recover_expired_content_work", {"p_limit": limit}).execute().data)

    def record_failure(self, claim: ContentClaim, *, failure_code: str,
                       failure_class: str, explicit_retry: bool) -> str:
        return fenced_rpc(self.client, "record_content_work_failure", claim,
            p_failure_code=failure_code, p_failure_class=failure_class, p_explicit_retry=explicit_retry)
