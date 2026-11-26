-- DeepLingo v3 migration 018: per-user concept mastery.

create table if not exists v3.concept_mastery (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  recognition numeric(4,3) not null default 0,
  comprehension numeric(4,3) not null default 0,
  listening numeric(4,3) not null default 0,
  recall numeric(4,3) not null default 0,
  production numeric(4,3) not null default 0,
  speaking numeric(4,3) not null default 0,
  overall numeric(4,3) not null default 0,
  confidence numeric(4,3) not null default 0,
  state v3.mastery_state not null default 'unknown',
  sample_count integer not null default 0,
  last_seen_at timestamptz,
  last_assessed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, concept_id),
  constraint concept_mastery_scores_chk check (
    recognition between 0 and 1 and
    comprehension between 0 and 1 and
    listening between 0 and 1 and
    recall between 0 and 1 and
    production between 0 and 1 and
    speaking between 0 and 1 and
    overall between 0 and 1 and
    confidence between 0 and 1
  ),
  constraint concept_mastery_sample_count_chk check (sample_count >= 0)
);

comment on table v3.concept_mastery is
  'Stores mastery calculated by the backend MasteryUpdater. No SQL trigger calculates overall.';
