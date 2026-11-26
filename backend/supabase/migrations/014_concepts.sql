-- DeepLingo v3 migration 014: canonical learnable concepts.

create table if not exists v3.concepts (
  id uuid primary key default extensions.gen_random_uuid(),
  language_code text not null references v3.languages(code) on delete restrict,
  type v3.concept_type not null,
  canonical_text text not null,
  normalized_text text not null,
  difficulty_level text,
  difficulty_score numeric(4,3),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint concepts_unique_normalized unique (language_code, type, normalized_text),
  constraint concepts_canonical_not_blank_chk check (length(btrim(canonical_text)) > 0),
  constraint concepts_normalized_not_blank_chk check (length(btrim(normalized_text)) > 0),
  constraint concepts_difficulty_score_chk check (difficulty_score is null or difficulty_score between 0 and 1),
  constraint concepts_metadata_object_chk check (jsonb_typeof(metadata) = 'object')
);

comment on table v3.concepts is
  'Canonical learning entity. Contains no user mastery and no video-specific evidence.';
