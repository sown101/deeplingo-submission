from uuid import UUID

from postgrest.types import ReturnMethod

from app.modules.content.application.knowledge_resolution import normalize_reference_text
from app.modules.content.domain.knowledge import DictionaryEntry
from app.modules.content.domain.pinyin import readable_pinyin
from app.platform.persistence import IN_CHUNK, V3Repository


class DictionaryEntryRepository(V3Repository):
    table_name = "dictionary_entries"

    def count_by_level(self, language_code: str, field: str, value: str) -> int:
        result = (self.table().select("id", count="exact").eq("language_code", language_code)
                  .eq(f"provider_metadata->>{field}", value).limit(1).execute())
        return result.count or 0

    def page_by_level(self, language_code: str, field: str, value: str, *, offset: int, limit: int) -> list[dict]:
        result = (self.table().select("*").eq("language_code", language_code)
                  .eq(f"provider_metadata->>{field}", value).order("normalized_headword")
                  .range(offset, offset + limit - 1).execute())
        return list(result.data or [])

    def rows_for_texts(self, language_code: str, texts: list[str]) -> list[dict]:
        normalized = list(dict.fromkeys(normalize_reference_text(text, language_code=language_code) for text in texts if text))
        rows: list[dict] = []
        for start in range(0, len(normalized), 200):
            result = (self.table().select("*").eq("language_code", language_code)
                      .in_("normalized_headword", normalized[start:start + 200]).limit(1000).execute())
            rows.extend(result.data or [])
        return rows

    def rows_containing(self, language_code: str, text: str, *, limit: int) -> list[dict]:
        needle = normalize_reference_text(text, language_code=language_code).replace("%", "").replace("_", "")
        if not needle:
            return []
        result = (self.table().select("*").eq("language_code", language_code)
                  .like("normalized_headword", f"%{needle}%").neq("normalized_headword", needle)
                  .not_.is_("provider_metadata->>hsk", "null").limit(limit).execute())
        return list(result.data or [])

    def has_headword(self, language_code: str, text: str) -> bool:
        result = (self.table().select("id").eq("language_code", language_code)
                  .eq("normalized_headword", normalize_reference_text(text, language_code=language_code)).limit(1).execute())
        return bool(result.data)

    def readings_for(self, language_code: str, texts: list[str]) -> dict[str, tuple[str | None, str | None]]:
        """Each word's reading and, for Chinese, its traditional form. A word with no entry is left out."""
        found: dict[str, tuple[str | None, str | None]] = {}
        for row in self.rows_for_texts(language_code, texts):
            key = row["normalized_headword"]
            reading = row.get("pronunciation")
            reading = readable_pinyin(reading) if language_code == "zh" else reading
            traditional = next((sense.get("traditional") for sense in row.get("definitions") or []
                                if isinstance(sense, dict) and sense.get("traditional")), None)
            if key not in found or (found[key][0] is None and reading):
                found[key] = (reading, traditional)
        return {text: found[key] for text in texts if (key := normalize_reference_text(text, language_code=language_code)) in found}

    def first_sense(self, entry_id) -> dict | None:
        """The headword and first sense of an entry, as stored."""
        result = self.table().select("id,headword,definitions,language_code").eq("id", str(entry_id)).limit(1).execute()
        rows = result.data or []
        if not rows:
            return None
        senses = [sense for sense in rows[0].get("definitions") or [] if isinstance(sense, dict) and sense.get("sense_id")]
        return {"headword": rows[0]["headword"], "language_code": rows[0]["language_code"], "sense": senses[0]} if senses else None

    def get_by_id(self, dictionary_entry_id) -> DictionaryEntry | None:
        result = self.table().select("*").eq("id", str(dictionary_entry_id)).limit(1).execute()
        rows = result.data or []
        return DictionaryEntry(**rows[0]) if rows else None

    def get_many_by_ids(self, entry_ids: list[UUID]) -> dict[UUID, DictionaryEntry]:
        ids = list(dict.fromkeys(str(key) for key in entry_ids))
        entries = {}
        for start in range(0, len(ids), IN_CHUNK):
            rows = self.table().select("*").in_("id", ids[start:start + IN_CHUNK]).execute().data or []
            entries.update({entry.id: entry for entry in map(DictionaryEntry.model_validate, rows)})
        return entries

    def get_by_normalized(
        self,
        *,
        language_code: str,
        normalized_headword: str,
        part_of_speech: str = "",
    ) -> DictionaryEntry | None:
        result = (
            self.table()
            .select("*")
            .eq("language_code", language_code)
            .eq("normalized_headword", normalized_headword)
            .eq("part_of_speech", part_of_speech)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return DictionaryEntry(**rows[0]) if rows else None

    def list_by_headwords(self, *, language_code: str, normalized_headwords: list[str]) -> list[DictionaryEntry]:
        """One round trip for every candidate unit of a word lookup."""
        return [DictionaryEntry(**row) for row in self.list_rows_by_headwords(
            language_code=language_code, normalized_headwords=normalized_headwords)]

    def list_rows_by_headwords(self, *, language_code: str, normalized_headwords: list[str]) -> list[dict]:
        """Full rows for re-upserting enriched metadata (word-level imports)."""
        if not normalized_headwords:
            return []
        result = (
            self.table()
            .select("*")
            .eq("language_code", language_code)
            .eq("part_of_speech", "")
            .in_("normalized_headword", normalized_headwords)
            .limit(len(normalized_headwords))
            .execute()
        )
        return list(result.data or [])

    def upsert_many(self, rows: list[dict]) -> int:
        """Bulk upsert on the reference key; used by dictionary imports."""
        if not rows:
            return 0
        result = (
            self.table()
            .upsert(rows, on_conflict="language_code,normalized_headword,part_of_speech",
                    returning=ReturnMethod.minimal)
            .execute()
        )
        _ = result
        return len(rows)

    def upsert_by_lookup(self, data: dict) -> DictionaryEntry:
        result = (
            self.table()
            .upsert(data, on_conflict="language_code,normalized_headword,part_of_speech")
            .execute()
        )
        return DictionaryEntry(**result.data[0])
