-- DeepLingo v3 migration 009: timed transcript segments.

create table if not exists v3.transcript_segments (
  id uuid primary key default extensions.gen_random_uuid(),
  transcript_id uuid not null references v3.video_transcripts(id) on delete cascade,
  sequence_number integer not null,
  start_ms integer not null,
  end_ms integer not null,
  text text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint transcript_segments_unique_sequence unique (transcript_id, sequence_number),
  constraint transcript_segments_sequence_positive_chk check (sequence_number > 0),
  constraint transcript_segments_time_chk check (start_ms >= 0 and end_ms > start_ms),
  constraint transcript_segments_text_not_blank_chk check (length(btrim(text)) > 0)
);
