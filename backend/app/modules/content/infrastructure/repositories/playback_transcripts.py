from app.platform.persistence import V3Repository


class PlaybackTranscriptRepository(V3Repository):
    table_name = "transcript_segments"

    def list_aggregate(self, transcript_id):
        # Page the join so long videos do not silently stop at the API row limit.
        # One mobile request; no per-segment repository requests.
        rows = []
        for offset in range(0, 10000, 500):
            result = (
                self.table()
                .select("id,sequence_number,text,start_ms,end_ms,"
                        "segment_translations(language_code,text),"
                        "segment_romanizations(text,romanization_systems(code,is_active)),"
                        "learning_objects(id,concept_id,start_codepoint,end_codepoint,evidence_text,"
                        "raw_ai_diagnostics,concepts(id,sense_key,language_code,type,metadata))")
                .eq("transcript_id", str(transcript_id))
                .order("sequence_number")
                .range(offset, offset + 499)
                .execute()
            )
            page = result.data or []
            rows.extend(page)
            if len(page) < 500:
                return rows
        raise ValueError("Transcript exceeds supported size")
