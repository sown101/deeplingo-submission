-- ADR-018 phase 2: learner-owned companion memory and the learner's memory consent.
--
-- Memory is companion context only: no pedagogical authority (scores, Evidence, mastery,
-- review, progression) reads it. It holds short structured notes, never audio or full
-- transcripts. Learners read their own rows; every write goes through authenticated
-- FastAPI routes that derive CurrentUser.id (service role). Forward-only.

create table if not exists v3.learner_companion_settings (
  user_id uuid primary key references v3.profiles(id) on delete cascade,
  -- null = never asked, true = learner allowed memory, false = learner declined.
  memory_enabled boolean,
  decided_at timestamptz,
  updated_at timestamptz not null default now()
);

comment on table v3.learner_companion_settings is
  'ADR-018: the learner''s companion memory consent. Server-written; learners read their own row.';

create table if not exists v3.learner_companion_memory (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  kind text not null,
  text text not null,
  example_quote text,
  concept_id uuid references v3.concepts(id) on delete cascade,
  usage_count integer not null default 1,
  source_entry text,
  model text,
  prompt_version text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '180 days'),
  constraint learner_companion_memory_kind_check check (
    kind in ('interest', 'recurring_error', 'practised_item', 'preference', 'session_summary')),
  constraint learner_companion_memory_text_check check (char_length(text) between 1 and 300),
  constraint learner_companion_memory_quote_check check (
    example_quote is null or char_length(example_quote) between 1 and 200),
  constraint learner_companion_memory_item_check check (
    (kind = 'practised_item') = (concept_id is not null)),
  constraint learner_companion_memory_count_check check (usage_count >= 1),
  constraint learner_companion_memory_entry_check check (
    source_entry is null or source_entry in ('video', 'review', 'home'))
);

comment on table v3.learner_companion_memory is
  'ADR-018: short structured notes the voice companion keeps about a consenting learner. '
  'Context only; never read by grading, mastery, review or progression. Expires after 180 days.';

create index if not exists learner_companion_memory_user_recent_idx
  on v3.learner_companion_memory (user_id, language_code, created_at desc);

create unique index if not exists learner_companion_memory_one_item_idx
  on v3.learner_companion_memory (user_id, language_code, concept_id)
  where kind = 'practised_item';

alter table v3.learner_companion_settings enable row level security;
alter table v3.learner_companion_memory enable row level security;

revoke all privileges on v3.learner_companion_settings from anon, authenticated;
revoke all privileges on v3.learner_companion_memory from anon, authenticated;
grant select on v3.learner_companion_settings to authenticated;
grant select on v3.learner_companion_memory to authenticated;
grant all privileges on v3.learner_companion_settings to service_role;
grant all privileges on v3.learner_companion_memory to service_role;

drop policy if exists "Users can read own companion settings" on v3.learner_companion_settings;
create policy "Users can read own companion settings"
  on v3.learner_companion_settings for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own companion memory" on v3.learner_companion_memory;
create policy "Users can read own companion memory"
  on v3.learner_companion_memory for select
  to authenticated
  using ((select auth.uid()) = user_id);
