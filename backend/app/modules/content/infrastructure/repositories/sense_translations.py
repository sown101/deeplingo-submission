"""M1 S7d: dictionary senses in a support language (`dictionary_sense_translations`, global content).

The first stored meaning of a sense and language is kept. Writes come from lookups, dictionary search
and claimed enrichment; Quick review reads them so it never calls a model while building a batch.
"""
from __future__ import annotations

import logging
from uuid import UUID

from app.platform.persistence import V3Repository

logger = logging.getLogger(__name__)
MAX_MEANING_CHARS = 160


class SenseTranslationRepository(V3Repository):
    table_name = "dictionary_sense_translations"

    def save(self, rows: list[dict]) -> None:
        """Insert-if-missing; never overwrites a stored meaning."""
        clean = [row for row in rows if row.get("meaning") and 0 < len(row["meaning"].strip()) <= MAX_MEANING_CHARS]
        if not clean:
            return
        self.table().upsert(
            [{**row, "dictionary_entry_id": str(row["dictionary_entry_id"]), "meaning": row["meaning"].strip()}
             for row in clean],
            on_conflict="dictionary_entry_id,sense_id,support_language_code", ignore_duplicates=True,
        ).execute()

    def for_senses(self, senses: list[tuple[UUID, str]], *, support_language_code: str) -> dict[tuple[UUID, str], dict]:
        if not senses:
            return {}
        entries = list(dict.fromkeys(str(entry) for entry, _ in senses))
        rows = (self.table().select("dictionary_entry_id,sense_id,headword,meaning,part_of_speech")
                .eq("support_language_code", support_language_code).in_("dictionary_entry_id", entries)
                .execute().data or [])
        wanted = set(senses)
        return {(UUID(row["dictionary_entry_id"]), row["sense_id"]): row for row in rows
                if (UUID(row["dictionary_entry_id"]), row["sense_id"]) in wanted}

    def sample(self, *, language_code: str, support_language_code: str, limit: int) -> list[dict]:
        return (self.table().select("headword,meaning,part_of_speech")
                .eq("language_code", language_code).eq("support_language_code", support_language_code)
                .order("created_at", desc=True).limit(limit).execute().data or [])
