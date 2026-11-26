-- ADR-020 phase 3: example sentences for words that have no video occurrence.
--
-- An ExampleSentence is shared reference content owned by the content module. It is not a
-- LearningObject: a LearningObject stays one exact trusted video occurrence. Rows come from a
-- dictionary example or, when none exists, from a validated generated sentence (labelled
-- "written by AI" in the clients). Writes go through the authenticated FastAPI routes using
-- the service role; clients have no grant. Deleting learner test data never deletes these rows.
-- Forward-only.

create table if not exists v3.example_sentences (
  id uuid primary key default gen_random_uuid(),
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  text text not null check (char_length(text) between 1 and 240),
  text_key text not null check (char_length(text_key) between 1 and 240),
  target_form text not null check (char_length(target_form) between 1 and 160),
  start_codepoint integer check (start_codepoint is null or start_codepoint >= 0),
  end_codepoint integer,
  translation text check (translation is null or char_length(translation) between 1 and 300),
  translation_language_code text references v3.languages(code) on delete restrict,
  source_kind text not null check (source_kind in ('occurrence', 'dictionary', 'corpus', 'generated')),
  source_ref text,
  license text,
  prompt_version text,
  model_name text,
  validation jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint example_sentences_span_check check (
    (start_codepoint is null and end_codepoint is null)
    or (start_codepoint is not null and end_codepoint is not null and end_codepoint > start_codepoint)
  ),
  constraint example_sentences_generated_trace_check check (
    source_kind <> 'generated' or (prompt_version is not null and model_name is not null)
  ),
  constraint example_sentences_translation_language_check check (
    translation is null or translation_language_code is not null
  )
);

comment on table v3.example_sentences is
  'ADR-020: example sentences for a Concept (dictionary or generated). Not a LearningObject; '
  'shared content, never learner state. Written only by authenticated FastAPI routes.';

create unique index if not exists example_sentences_concept_text_uidx
  on v3.example_sentences (concept_id, source_kind, text_key);
create index if not exists example_sentences_concept_idx
  on v3.example_sentences (concept_id, created_at);

alter table v3.example_sentences enable row level security;
revoke all privileges on v3.example_sentences from anon, authenticated;
grant all privileges on v3.example_sentences to service_role;
