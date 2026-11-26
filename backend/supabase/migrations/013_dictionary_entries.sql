-- DeepLingo v3 migration 013: dictionary reference entries.

create table if not exists v3.dictionary_entries (
  id uuid primary key default extensions.gen_random_uuid(),
  language_code text not null references v3.languages(code) on delete restrict,
  headword text not null,
  normalized_headword text not null,
  part_of_speech text not null default '',
  pronunciation text,
  definitions jsonb not null default '[]'::jsonb,
  examples jsonb not null default '[]'::jsonb,
  provider text,
  provider_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint dictionary_entries_unique_headword unique (language_code, normalized_headword, part_of_speech),
  constraint dictionary_entries_headword_not_blank_chk check (length(btrim(headword)) > 0),
  constraint dictionary_entries_normalized_not_blank_chk check (length(btrim(normalized_headword)) > 0),
  constraint dictionary_entries_definitions_array_chk check (jsonb_typeof(definitions) = 'array'),
  constraint dictionary_entries_examples_array_chk check (jsonb_typeof(examples) = 'array'),
  constraint dictionary_entries_provider_metadata_object_chk check (jsonb_typeof(provider_metadata) = 'object')
);

comment on table v3.dictionary_entries is
  'Linguistic reference information. Not the learner-facing canonical concept.';
