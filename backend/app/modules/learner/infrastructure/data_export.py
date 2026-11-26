"""Learner-module rows for the learner data export (profile, languages, progress, organisation, voice consent,
personalization signals and, FR-3.11, the transcript consent and kept spoken turns)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.learner.domain.speech_transcripts import retention_cutoff
from app.platform.persistence import select_optional_rows, select_rows

TRANSCRIPT_COLUMNS = ("session_id,turn_index,language_code,library_item_id,topic,assistance_level,agent_text,"
                      "learner_text,recognized_text,word_scores,grammar_errors,occurred_at,created_at")


class LearnerOwnDataSection:
    name = "learner"

    def __init__(self, client: Any):
        self.client = client

    def export(self, user_id: UUID) -> dict[str, Any]:
        uid = str(user_id)

        def rows(table: str, columns: str, column: str = "user_id", *, optional: bool = False) -> list[dict]:
            read = select_optional_rows if optional else select_rows
            return read(self.client, table, columns, filters={column: uid})

        groups = rows("word_groups", "id,language_code,name,color,description,created_at")
        group_items = select_rows(self.client, "word_group_items", "group_id,saved_concept_id,added_at", filters={},
                                  in_filter=("group_id", [group["id"] for group in groups]))
        profile = rows("profiles", "display_name,timezone,created_at", column="id")
        transcript_consent = (rows("learner_agent_consent", "transcript_consent,transcript_decided_at",
                                   optional=True) or [None])[0]
        cutoff = retention_cutoff(datetime.now(UTC))
        transcripts = [row for row in rows("learner_speech_transcripts", TRANSCRIPT_COLUMNS, optional=True)
                       if datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00")) > cutoff]
        return {
            "profile": profile[0] if profile else None,
            "language_preferences": rows(
                "user_language_preferences",
                "language_code,support_language_code,target_level,declared_level,daily_new_limit,learning_goal,is_primary,"
                "created_at,updated_at"),
            "saved_concepts": rows(
                "saved_concepts",
                "id,concept_id,note,save_source,created_at,status,explicit,priority,level_label,rung,activated_at,"
                "language_code,favorite"),
            "target_events": rows("target_events", "concept_id,kind,outcome,context_key,quote,error_type,occurred_at"),
            "video_words": rows("learner_video_words", "library_item_id,concept_id,created_at"),
            "word_groups": [{**group, "items": [item for item in group_items if item["group_id"] == group["id"]]}
                            for group in groups],
            "voice_consent": (rows("learner_agent_consent", "voice_consent,decided_at,updated_at") or [None])[0],
            "personalization_signals": rows(
                "learner_personalization_signals", "language_code,kind,code,usage_count,created_at,updated_at"),
            "transcript_consent": transcript_consent,
            "pronunciation_scores": rows("learner_pronunciation_scores",
                                         "occurred_at,language_code,source,pronunciation,accuracy,fluency,weak_words",
                                         optional=True),
            "speech_transcripts": sorted(transcripts, key=lambda row: (str(row["occurred_at"]), row["turn_index"])),
        }
