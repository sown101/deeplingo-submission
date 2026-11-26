-- PRD FR-4.2 (Q11): every recorded speaking session counts towards the practice streak, whether or not it
-- touched a saved word. This table holds only that a session happened: no audio, text, score or quote.
-- Forward-only. Applying it to any environment needs the owner's approval for that environment.
-- Until it is applied the streak simply does not count speaking sessions (the app tolerates the missing table).

create table if not exists v3.learner_speaking_activity (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  source text not null,
  seconds integer not null default 0,
  -- How many times the learner spoke and which of their saved words the app had to show them (names only).
  turns integer not null default 0,
  reuse_words text[] not null default '{}',
  occurred_at timestamptz not null default now(),
  constraint learner_speaking_activity_source_check check (source in ('conversation', 'shadowing', 'jam')),
  constraint learner_speaking_activity_seconds_check check (seconds between 0 and 7200),
  constraint learner_speaking_activity_turns_check check (turns between 0 and 1000),
  constraint learner_speaking_activity_words_check check (cardinality(reuse_words) <= 6)
);

comment on table v3.learner_speaking_activity is
  'FR-4.2: one row per speaking session (conversation, Shadowing or JAM) for the practice streak. Derived facts only.';

create index if not exists learner_speaking_activity_user_idx
  on v3.learner_speaking_activity (user_id, occurred_at desc);

alter table v3.learner_speaking_activity enable row level security;
revoke all privileges on v3.learner_speaking_activity from anon, authenticated;
grant select on v3.learner_speaking_activity to authenticated;
grant all privileges on v3.learner_speaking_activity to service_role;

drop policy if exists "Users can read own speaking activity" on v3.learner_speaking_activity;
create policy "Users can read own speaking activity"
  on v3.learner_speaking_activity for select
  to authenticated
  using ((select auth.uid()) = user_id);
