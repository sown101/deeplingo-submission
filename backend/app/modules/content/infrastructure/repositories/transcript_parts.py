from app.platform.persistence import V3Repository


class TranscriptPartsCache(V3Repository):
    """Shared content: the model's study parts of one transcript version; no learner identifiers."""

    table_name = "transcript_parts"

    def get(self, transcript_id, version):
        rows = (self.table().select("parts").eq("transcript_id", str(transcript_id)).eq("version", version)
                .limit(1).execute()).data or []
        return rows[0]["parts"] if rows else None

    def save(self, transcript_id, version, parts):
        self.table().upsert({"transcript_id": str(transcript_id), "version": version, "parts": parts},
                           on_conflict="transcript_id,version").execute()
