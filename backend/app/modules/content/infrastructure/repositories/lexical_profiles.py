"""Stored word profiles of transcripts (`video_lexical_profiles`, `video_lexemes`) and the segment texts they are built from (L1c).

Service-role only: the rows are derived server data. The profile row is written last, so a profile row
means its lexemes are complete; a rebuild replaces the lexemes first and then the profile row."""
from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from app.modules.content.application.lexical_profile import Lexeme, StoredProfile
from app.platform.persistence import V3Repository, fetch_pages

PAGE = 1000  # PostgREST returns at most this many rows per read
INSERT_CHUNK = 500
MAX_PAGES = 200


def _transcript_rows(table, transcript_ids: list[UUID], columns: str, order: str) -> dict[UUID, list[dict]]:
    if not transcript_ids:
        return {}
    query = (table().select(f"transcript_id,{columns}").in_("transcript_id", [str(key) for key in transcript_ids])
             .order("transcript_id").order(order))
    limit = MAX_PAGES * PAGE * len(transcript_ids)
    rows = fetch_pages(query, limit + 1)
    if len(rows) > limit:
        raise ValueError("Too many transcript rows to read in one batch")
    grouped = defaultdict(list)
    for row in rows:
        grouped[UUID(row["transcript_id"])].append(row)
    return grouped


def _lexemes(rows: list[dict]) -> list[Lexeme]:
    return [Lexeme(row["lexeme"], row.get("level_label"), bool(row["matched"]), int(row["occurrences"]),
                   bool(row.get("level_derived"))) for row in rows]


def _stored_profile(row: dict) -> StoredProfile:
    return StoredProfile(UUID(str(row["transcript_id"])), row["language_code"], int(row["profile_version"]),
                         int(row["token_count"]), int(row["proper_noun_count"]), int(row["speech_ms"]),
                         row.get("source_hash"))


def _spans(rows: list[dict]) -> list[tuple[int, int, str]]:
    return [(int(row["start_ms"]), int(row["end_ms"]), str(row["text"])) for row in rows]


class LexemeRepository(V3Repository):
    table_name = "video_lexemes"

    def list_for_transcript(self, transcript_id: UUID) -> list[Lexeme]:
        rows: list[dict] = []
        for page in range(MAX_PAGES):
            chunk = (self.table().select("lexeme,level_label,matched,occurrences,level_derived")
                     .eq("transcript_id", str(transcript_id)).order("lexeme")
                     .range(page * PAGE, page * PAGE + PAGE - 1).execute().data or [])
            rows.extend(chunk)
            if len(chunk) < PAGE:
                break
        return _lexemes(rows)

    def list_for_transcripts(self, transcript_ids: list[UUID]) -> dict[UUID, list[Lexeme]]:
        grouped = _transcript_rows(self.table, transcript_ids, "lexeme,level_label,matched,occurrences,level_derived", "lexeme")
        return {key: _lexemes(rows) for key, rows in grouped.items()}

    def replace(self, transcript_id: UUID, lexemes: list[Lexeme]) -> None:
        self.table().delete().eq("transcript_id", str(transcript_id)).execute()
        for start in range(0, len(lexemes), INSERT_CHUNK):
            self.table().insert([
                {"transcript_id": str(transcript_id), "lexeme": item.lexeme, "level_label": item.level,
                 "matched": item.matched, "occurrences": item.occurrences,
                 "level_derived": item.level_derived}
                for item in lexemes[start:start + INSERT_CHUNK]
            ]).execute()


class LexicalProfileRepository(V3Repository):
    table_name = "video_lexical_profiles"

    def __init__(self, client):
        super().__init__(client)
        self._lexemes = LexemeRepository(client)

    def get(self, transcript_id: UUID) -> StoredProfile | None:
        rows = (self.table().select("*").eq("transcript_id", str(transcript_id)).limit(1).execute().data or [])
        if not rows:
            return None
        return _stored_profile(rows[0])

    def get_many(self, transcript_ids: list[UUID]) -> dict[UUID, StoredProfile]:
        if not transcript_ids:
            return {}
        rows = self.table().select("*").in_("transcript_id", [str(key) for key in transcript_ids]).execute().data or []
        return {profile.transcript_id: profile for profile in map(_stored_profile, rows)}

    def lexemes(self, transcript_id: UUID) -> list[Lexeme]:
        return self._lexemes.list_for_transcript(transcript_id)

    def lexemes_for_many(self, transcript_ids: list[UUID]) -> dict[UUID, list[Lexeme]]:
        return self._lexemes.list_for_transcripts(transcript_ids)

    def replace(self, profile: StoredProfile, lexemes: list[Lexeme]) -> None:
        self._lexemes.replace(profile.transcript_id, lexemes)
        self.table().upsert({
            "transcript_id": str(profile.transcript_id), "language_code": profile.language_code,
            "profile_version": profile.version, "token_count": profile.token_count,
            "proper_noun_count": profile.proper_noun_count, "speech_ms": profile.speech_ms,
            "source_hash": profile.source_hash,
        }, on_conflict="transcript_id").execute()


class SegmentTextRepository(V3Repository):
    """Every segment of a transcript, read in pages (a long video has more than one page of rows)."""

    table_name = "transcript_segments"

    def spans_and_texts(self, transcript_id: UUID) -> list[tuple[int, int, str]]:
        rows: list[dict] = []
        for page in range(MAX_PAGES):
            chunk = (self.table().select("sequence_number,start_ms,end_ms,text")
                     .eq("transcript_id", str(transcript_id)).order("sequence_number")
                     .range(page * PAGE, page * PAGE + PAGE - 1).execute().data or [])
            rows.extend(chunk)
            if len(chunk) < PAGE:
                break
        return _spans(rows)

    def spans_and_texts_for_many(self, transcript_ids: list[UUID]) -> dict[UUID, list[tuple[int, int, str]]]:
        grouped = _transcript_rows(self.table, transcript_ids, "start_ms,end_ms,text", "sequence_number")
        return {key: _spans(rows) for key, rows in grouped.items()}
