-- L1a: learner targets (owner-approved plan of 2026-10-26). Forward-only and additive.
--
-- v3.saved_concepts becomes the learner's targets table. Every existing row is `active`, so current
-- behaviour does not change; new rows default to `backlog` and the application's daily gate moves at
-- most `daily_new_limit` of them to `active` per local day. `known` stays in
-- v3.learner_known_concepts, written only by v3.mark_concept_known.
--
-- v3.target_events is the append-only evidence behind the usage ladder (rungs R0 to R5); the rung
-- stored on the target is a projection that application code recomputes from these events.
--
-- v3.user_language_preferences gets the learner's declared level and daily new limit.
--
-- Not applied to any environment by this file's author. Applying it needs the owner's approval.

-- 1. saved_concepts -> targets ------------------------------------------------------------------

alter table v3.saved_concepts add column if not exists language_code text
  references v3.languages(code) on delete restrict;
alter table v3.saved_concepts add column if not exists status text not null default 'active';
alter table v3.saved_concepts add column if not exists explicit boolean not null default true;
alter table v3.saved_concepts add column if not exists priority integer not null default 0;
alter table v3.saved_concepts add column if not exists level_label text;
alter table v3.saved_concepts add column if not exists activated_at timestamptz;
alter table v3.saved_concepts add column if not exists rung smallint not null default 0;

update v3.saved_concepts as s
   set language_code = c.language_code
  from v3.concepts as c
 where c.id = s.concept_id and s.language_code is null;

update v3.saved_concepts
   set activated_at = created_at
 where activated_at is null and status = 'active';

-- Rows written from now on start in the backlog unless the application says otherwise.
alter table v3.saved_concepts alter column status set default 'backlog';

alter table v3.saved_concepts drop constraint if exists saved_concepts_status_check;
alter table v3.saved_concepts add constraint saved_concepts_status_check
  check (status in ('backlog', 'active', 'suspended'));

alter table v3.saved_concepts drop constraint if exists saved_concepts_rung_check;
alter table v3.saved_concepts add constraint saved_concepts_rung_check
  check (rung between 0 and 5);

alter table v3.saved_concepts drop constraint if exists saved_concepts_priority_check;
alter table v3.saved_concepts add constraint saved_concepts_priority_check
  check (priority between 0 and 1000);

alter table v3.saved_concepts drop constraint if exists saved_concepts_active_activated_check;
alter table v3.saved_concepts add constraint saved_concepts_active_activated_check
  check (status <> 'active' or activated_at is not null);

alter table v3.saved_concepts drop constraint if exists saved_concepts_save_source_check;
alter table v3.saved_concepts add constraint saved_concepts_save_source_check
  check (save_source is null or save_source in ('lookup', 'manual', 'occurrence', 'import', 'content'));

comment on column v3.saved_concepts.status is
  'backlog: waiting for the daily gate. active: being learned (new cards are built). suspended: paused by the learner.';
comment on column v3.saved_concepts.explicit is
  'true when the learner saved or imported the word; false for a lookup the system queued on its own.';
comment on column v3.saved_concepts.priority is
  'Higher is activated first. Explicit save 100, lookup 50, import 40, content 10.';
comment on column v3.saved_concepts.level_label is
  'CEFR label (A1..C2) or HSK label (HSK1..HSK7) of the Concept when known; null when unclassified.';
comment on column v3.saved_concepts.rung is
  'Usage ladder R0..R5, a projection of v3.target_events recomputed by the application.';

create index if not exists saved_concepts_user_language_status_idx
  on v3.saved_concepts (user_id, language_code, status, priority desc, created_at);

-- 2. target_events ------------------------------------------------------------------------------

create table if not exists v3.target_events (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  kind text not null,
  outcome text not null,
  event_key text not null,
  context_key text,
  quote text,
  error_type text,
  judge jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint target_events_kind_check
    check (kind in ('seen', 'recognition', 'recall', 'framed_use', 'spontaneous_use')),
  constraint target_events_outcome_check check (outcome in ('correct', 'incorrect')),
  constraint target_events_judge_object_check check (jsonb_typeof(judge) = 'object'),
  constraint target_events_event_key_unique unique (user_id, event_key)
);

comment on table v3.target_events is
  'Append-only evidence for the usage ladder. Never updated or deleted by the application, except with the learner''s data.';

create index if not exists target_events_user_concept_idx
  on v3.target_events (user_id, concept_id, occurred_at);

alter table v3.target_events enable row level security;
revoke all privileges on v3.target_events from anon, authenticated;
grant select on v3.target_events to authenticated;
grant all privileges on v3.target_events to service_role;

drop policy if exists "Users can read own target events" on v3.target_events;
create policy "Users can read own target events"
  on v3.target_events for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- 3. language preferences -----------------------------------------------------------------------

alter table v3.user_language_preferences add column if not exists declared_level text;
alter table v3.user_language_preferences add column if not exists daily_new_limit smallint not null default 10;

alter table v3.user_language_preferences drop constraint if exists user_language_preferences_declared_level_check;
alter table v3.user_language_preferences add constraint user_language_preferences_declared_level_check
  check (declared_level is null or declared_level in
    ('A1', 'A2', 'A2+', 'B1', 'B1+', 'B2', 'B2+', 'HSK1', 'HSK2', 'HSK3', 'HSK4', 'HSK5', 'HSK6'));

alter table v3.user_language_preferences drop constraint if exists user_language_preferences_daily_new_limit_check;
alter table v3.user_language_preferences add constraint user_language_preferences_daily_new_limit_check
  check (daily_new_limit between 1 and 50);

comment on column v3.user_language_preferences.declared_level is
  'Self-declared level: CEFR for English, HSK 1..6 for Chinese. Used only to warn about out-of-level words.';
comment on column v3.user_language_preferences.daily_new_limit is
  'How many backlog targets the daily gate activates per local day (default 10).';
