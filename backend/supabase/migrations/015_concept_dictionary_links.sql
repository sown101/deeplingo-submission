-- DeepLingo v3 migration 015: many-to-many concept/dictionary support links.

create table if not exists v3.concept_dictionary_links (
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  dictionary_entry_id uuid not null references v3.dictionary_entries(id) on delete cascade,
  relation_type text not null default 'supports',
  created_at timestamptz not null default now(),
  primary key (concept_id, dictionary_entry_id),
  constraint concept_dictionary_links_relation_chk check (
    relation_type in ('supports', 'component', 'headword', 'variant')
  )
);

comment on table v3.concept_dictionary_links is
  'Explicit many-to-many relationship. One dictionary entry can support multiple concepts and vice versa.';
