-- DeepLingo v3 migration 010: segment translations.

create table if not exists v3.segment_translations (
  transcript_segment_id uuid not null references v3.transcript_segments(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  text text not null,
  source v3.content_source not null default 'ai',
  confidence numeric(4,3),
  provider_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (transcript_segment_id, language_code),
  constraint segment_translations_confidence_chk check (confidence is null or confidence between 0 and 1),
  constraint segment_translations_text_not_blank_chk check (length(btrim(text)) > 0),
  constraint segment_translations_provider_metadata_object_chk check (jsonb_typeof(provider_metadata) = 'object')
);
