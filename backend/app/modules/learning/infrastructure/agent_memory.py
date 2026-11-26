"""What the agent remembers about a learner across conversations (PRD 8.12 point 3): short free-text rows.
Service-role only, with the learner named on every query; the table has no grant for anon or authenticated. Rows
are never logged. Where the table is not applied yet, reads give nothing and writes report failure, so a
conversation never fails because of memory."""
from __future__ import annotations

import logging
from uuid import UUID

from app.platform.persistence import V3Repository

logger = logging.getLogger(__name__)

MAX_ROWS = 40  # per learner: adding one more removes the oldest
LIST_COLUMNS = "id,kind,text,language_code,created_at"
# With the phase 5 columns (migration 20261122100000); an environment without them is read as before.
LIST_COLUMNS_WITH_EVIDENCE = LIST_COLUMNS + ",evidence,source"


class AgentMemoryRepository(V3Repository):
    table_name = "learner_agent_memory"

    def list_for_learner(self, user_id: UUID, *, limit: int = MAX_ROWS) -> list[dict]:
        """The learner's own rows, newest first; empty when they cannot be read."""
        for columns in (LIST_COLUMNS_WITH_EVIDENCE, LIST_COLUMNS):
            try:
                rows = (self.table().select(columns).eq("user_id", str(user_id))
                        .order("created_at", desc=True).limit(max(1, min(limit, MAX_ROWS))).execute().data or [])
            except Exception as exc:
                logger.warning("agent memory unavailable op=list error=%s", type(exc).__name__)
                continue
            return [dict(row) for row in rows]
        return []

    def add(self, user_id: UUID, *, kind: str, text: str, language_code: str | None,
            evidence: list[dict] | None = None, source: str = "agent") -> bool:
        """Stores one row; past MAX_ROWS the oldest ones are removed. One database function does the insert and the
        trim in one transaction, one writer per learner at a time. False when it could not be stored. A row with
        evidence needs the phase 5 function; where it is missing the row is stored without its evidence."""
        if evidence:
            try:
                stored = self.client.schema(self.schema).rpc("add_agent_memory_with_evidence", {
                    "p_user_id": str(user_id), "p_kind": kind, "p_text": text, "p_language_code": language_code,
                    "p_max_rows": MAX_ROWS, "p_evidence": evidence[:3], "p_source": source}).execute().data
                return bool(stored)
            except Exception as exc:
                logger.warning("agent memory evidence unavailable op=add error=%s", type(exc).__name__)
        try:
            stored = self.client.schema(self.schema).rpc("add_agent_memory", {
                "p_user_id": str(user_id), "p_kind": kind, "p_text": text, "p_language_code": language_code,
                "p_max_rows": MAX_ROWS}).execute().data
            return bool(stored)
        except Exception as exc:
            logger.warning("agent memory unavailable op=add error=%s", type(exc).__name__)
            return False

    def delete_one(self, user_id: UUID, memory_id: UUID) -> bool:
        """True when this learner's row existed and was removed; another learner's id removes nothing."""
        try:
            result = (self.table().delete().eq("user_id", str(user_id)).eq("id", str(memory_id)).execute())
        except Exception as exc:
            logger.warning("agent memory unavailable op=delete_one error=%s", type(exc).__name__)
            return False
        return bool(result.data)

    def delete_all(self, user_id: UUID) -> bool:
        """True when the learner's rows are gone (also when there were none); False when it failed."""
        try:
            self.table().delete().eq("user_id", str(user_id)).execute()
        except Exception as exc:
            logger.warning("agent memory unavailable op=delete_all error=%s", type(exc).__name__)
            return False
        return True
