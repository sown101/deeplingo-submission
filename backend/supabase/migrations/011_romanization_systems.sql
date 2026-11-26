-- DeepLingo v3 migration 011: romanization/transliteration systems.

create table if not exists v3.romanization_systems (
  id uuid primary key default extensions.gen_random_uuid(),
  language_code text not null references v3.languages(code) on delete cascade,
  code text not null,
  name text not null,
  standard_status text not null default 'learner_friendly',
  notes text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint romanization_systems_unique_code unique (language_code, code),
  constraint romanization_systems_status_chk check (
    standard_status in ('official', 'standard', 'common', 'learner_friendly', 'informal', 'experimental')
  )
);

comment on table v3.romanization_systems is
  'A language may have multiple romanization/transliteration systems. Do not collapse this into one boolean/string pair.';
