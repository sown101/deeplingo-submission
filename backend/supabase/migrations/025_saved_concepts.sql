-- DeepLingo v3 migration 025: user-saved concepts.

create table if not exists v3.saved_concepts (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  source_learning_object_id uuid references v3.learning_objects(id) on delete set null,
  note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint saved_concepts_unique_concept unique (user_id, concept_id)
);

comment on table v3.saved_concepts is
  'User save/bookmark for a concept. Does not duplicate dictionary or vocabulary data.';
