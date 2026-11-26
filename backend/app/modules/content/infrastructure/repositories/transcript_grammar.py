from app.platform.persistence import V3Repository


class TranscriptGrammarCache(V3Repository):
    table_name = "transcript_grammar_explanations"

    def get(self, source_hash, support_language_code, version):
        rows = (self.table().select("explanation").eq("source_hash", source_hash)
                .eq("support_language_code", support_language_code).eq("version", version)
                .limit(1).execute()).data or []
        return rows[0]["explanation"] if rows else None

    def save(self, source_hash, support_language_code, version, explanation):
        self.table().upsert({"source_hash": source_hash, "support_language_code": support_language_code,
                            "version": version, "explanation": explanation},
                           on_conflict="source_hash,support_language_code,version").execute()
