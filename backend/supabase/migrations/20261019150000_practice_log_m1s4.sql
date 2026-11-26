-- M1 S4: the learner's practice log for one Library video (learning-owned).
--
-- Only events a later turn or session uses: a Dictation answer the server re-checked against the
-- transcript, a Shadowing attempt the server assessed, and a word the learner looked up in a
-- sentence. `origin` says whether the server observed or recomputed it (`observed`) or a model
-- inferred it (`inferred`, none yet). The payload is a bounded summary: no raw answer, audio or
-- transcript text beyond the looked-up words. Never an Attempt, Assessment, Evidence, mastery,
-- skill or ReviewState. One row per client UUID (idempotent retries); rows expire after 90 days
-- and go with the Library item or the profile. Learners read their own rows; writes go through
-- authenticated FastAPI routes (service role). Forward-only.

create table if not exists v3.learner_practice_events (
  id uuid primary key,
  user_id uuid not null references v3.profiles(id) on delete cascade,
  library_item_id uuid not null,
  kind text not null check (kind in ('dictation_checked', 'shadowing_attempted', 'word_lookup')),
  origin text not null check (origin in ('observed', 'inferred')),
  transcript_id uuid not null,
  segment_id uuid not null,
  payload jsonb not null default '{}'::jsonb
    check (jsonb_typeof(payload) = 'object' and pg_column_size(payload) <= 2048),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '90 days',
  constraint learner_practice_events_library_item_fkey
    foreign key (library_item_id, user_id)
    references v3.learner_videos (id, user_id) on delete cascade,
  constraint learner_practice_events_expiry_chk check (expires_at > created_at)
);

comment on table v3.learner_practice_events is
  'M1 S4: bounded practice-log summaries per Library item (Dictation re-checked by the server, '
  'Shadowing attempts, word lookups). Practice only: not Evidence, mastery or ReviewState; 90 days.';

create index if not exists learner_practice_events_recent_idx
  on v3.learner_practice_events (user_id, library_item_id, created_at desc);
create index if not exists learner_practice_events_expiry_idx
  on v3.learner_practice_events (user_id, expires_at);

alter table v3.learner_practice_events enable row level security;
revoke all privileges on v3.learner_practice_events from public, anon, authenticated;
grant select on v3.learner_practice_events to authenticated;
grant all privileges on v3.learner_practice_events to service_role;

drop policy if exists "Users can read own practice events" on v3.learner_practice_events;
create policy "Users can read own practice events"
  on v3.learner_practice_events for select
  to authenticated
  using ((select auth.uid()) = user_id);
