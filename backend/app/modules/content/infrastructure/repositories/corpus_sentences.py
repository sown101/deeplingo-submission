"""Licensed corpus sentences (`corpus_sentences`): service-role access only."""
from __future__ import annotations

from app.platform.persistence import V3Repository


class CorpusSentenceRepository(V3Repository):
    table_name = "corpus_sentences"

    def upsert_many(self, rows: list[dict]) -> int:
        """Idempotent on (source, source_id); returns the number of rows sent."""
        if not rows:
            return 0
        self.table().upsert(rows, on_conflict="source,source_id").execute()
        return len(rows)

    def find_candidates(self, *, language_code: str, form: str, translation_language: str,
                        limit: int = 20) -> list[dict]:
        result = self.client.schema(self.schema).rpc("find_corpus_sentences", {
            "p_language_code": language_code, "p_form": form,
            "p_translation_language": translation_language, "p_limit": limit,
        }).execute()
        return list(result.data or [])
