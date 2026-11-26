-- DeepLingo v3 migration 027: group membership.

create table if not exists v3.word_group_items (
  group_id uuid not null references v3.word_groups(id) on delete cascade,
  saved_concept_id uuid not null references v3.saved_concepts(id) on delete cascade,
  added_at timestamptz not null default now(),
  primary key (group_id, saved_concept_id)
);
