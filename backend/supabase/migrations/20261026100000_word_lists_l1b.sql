-- L1b: named word lists and bulk import (owner-approved plan of 2026-10-26). Forward-only and additive.
--
-- v3.word_groups and v3.word_group_items already exist (migrations 026 and 027) and are not used by the
-- application yet; they become the learner's named lists. A list item points at a target
-- (v3.saved_concepts.id). This adds:
--   * a case-insensitive unique list name per learner and language, and a name length limit;
--   * v3.word_group_import_rows: imported lines that are not yet a target (an ambiguous word waiting for
--     the learner to choose a meaning, or a word that is not in the dictionary).
--
-- Not applied to any environment by this file's author. Applying it needs the owner's approval.

alter table v3.word_groups drop constraint if exists word_groups_name_length_check;
alter table v3.word_groups add constraint word_groups_name_length_check check (length(name) <= 60);

create unique index if not exists word_groups_user_language_name_idx
  on v3.word_groups (user_id, language_code, lower(name));

create table if not exists v3.word_group_import_rows (
  id uuid primary key default extensions.gen_random_uuid(),
  group_id uuid not null references v3.word_groups(id) on delete cascade,
  user_id uuid not null references v3.profiles(id) on delete cascade,
  position integer not null,
  raw_text text not null,
  user_gloss text,
  resolution text not null,
  candidates jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  constraint word_group_import_rows_text_check check (length(btrim(raw_text)) between 1 and 120),
  constraint word_group_import_rows_gloss_check check (user_gloss is null or length(user_gloss) <= 300),
  constraint word_group_import_rows_resolution_check check (resolution in ('ambiguous', 'unresolved')),
  constraint word_group_import_rows_candidates_check
    check (jsonb_typeof(candidates) = 'array' and jsonb_array_length(candidates) <= 15),
  constraint word_group_import_rows_position_unique unique (group_id, position)
);

comment on table v3.word_group_import_rows is
  'Imported lines that are not targets yet: ambiguous (the learner picks one stored candidate meaning) or unresolved (not in the dictionary).';

create index if not exists word_group_import_rows_group_idx
  on v3.word_group_import_rows (group_id, position);

alter table v3.word_group_import_rows enable row level security;
revoke all privileges on v3.word_group_import_rows from anon, authenticated;
grant select on v3.word_group_import_rows to authenticated;
grant all privileges on v3.word_group_import_rows to service_role;

drop policy if exists "Users can read own import rows" on v3.word_group_import_rows;
create policy "Users can read own import rows"
  on v3.word_group_import_rows for select
  to authenticated
  using ((select auth.uid()) = user_id);
