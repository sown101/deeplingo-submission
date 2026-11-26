-- DeepLingo v3 migration 012: segment romanizations.

create table if not exists v3.segment_romanizations (
  transcript_segment_id uuid not null references v3.transcript_segments(id) on delete cascade,
  romanization_system_id uuid not null references v3.romanization_systems(id) on delete restrict,
  text text not null,
  source v3.content_source not null default 'hybrid',
  confidence numeric(4,3),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (transcript_segment_id, romanization_system_id),
  constraint segment_romanizations_confidence_chk check (confidence is null or confidence between 0 and 1),
  constraint segment_romanizations_text_not_blank_chk check (length(btrim(text)) > 0)
);
