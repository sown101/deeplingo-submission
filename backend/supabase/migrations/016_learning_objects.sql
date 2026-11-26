-- DeepLingo v3 migration 016: evidence-backed learning objects.

create table if not exists v3.learning_objects (
  id uuid primary key default extensions.gen_random_uuid(),
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  video_id uuid not null references v3.videos(id) on delete cascade,
  transcript_segment_id uuid not null references v3.transcript_segments(id) on delete cascade,
  occurrence_index integer not null default 1,
  evidence_text text not null,
  previous_context text,
  next_context text,
  start_ms integer not null,
  end_ms integer not null,
  difficulty_score numeric(4,3),
  learning_value_score numeric(4,3),
  ai_confidence numeric(4,3),
  extraction_status v3.extraction_status not null default 'candidate',
  source v3.content_source not null default 'ai',
  supported_activity_types v3.activity_type[] not null default array[]::v3.activity_type[],
  raw_ai_diagnostics jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint learning_objects_unique_occurrence unique (concept_id, transcript_segment_id, occurrence_index),
  constraint learning_objects_occurrence_index_chk check (occurrence_index > 0),
  constraint learning_objects_time_chk check (start_ms >= 0 and end_ms > start_ms),
  constraint learning_objects_evidence_not_blank_chk check (length(btrim(evidence_text)) > 0),
  constraint learning_objects_difficulty_score_chk check (difficulty_score is null or difficulty_score between 0 and 1),
  constraint learning_objects_learning_value_score_chk check (learning_value_score is null or learning_value_score between 0 and 1),
  constraint learning_objects_ai_confidence_chk check (ai_confidence is null or ai_confidence between 0 and 1),
  constraint learning_objects_raw_ai_diagnostics_object_chk check (
    raw_ai_diagnostics is null or jsonb_typeof(raw_ai_diagnostics) = 'object'
  )
);

comment on table v3.learning_objects is
  'Context-specific learning opportunity with evidence. Does not store generated exercise content.';
comment on column v3.learning_objects.video_id is
  'Invariant: transcript_segment_id must belong to a transcript for this video. Enforce in service code or future composite constraint.';
