-- PRD FR-3.4 / FR-3.6: the learner's one revocable voice consent and the agent's personalization
-- signals. A signal is a closed code (topic group, stated goal, recurring error type, fluency
-- level), never text, so names, places, workplaces, quotes and source text cannot be stored.
-- The lists below mirror app/modules/learner/domain/agent_signals.py (a test keeps them equal).
-- Learners read their own rows; every write goes through authenticated FastAPI routes that
-- derive CurrentUser.id (service role). Forward-only. The old companion memory tables are not
-- touched here; dropping them is a separate, separately approved migration.

create table if not exists v3.learner_agent_consent (
  user_id uuid primary key references v3.profiles(id) on delete cascade,
  -- null = never asked, true = granted, false = revoked.
  voice_consent boolean,
  decided_at timestamptz,
  updated_at timestamptz not null default now()
);

comment on table v3.learner_agent_consent is
  'FR-3.4: the learner''s single, revocable consent to voice processing by the agent (including sending audio for pronunciation scoring). Server-written; learners read their own row.';

create table if not exists v3.learner_personalization_signals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  kind text not null,
  code text not null,
  usage_count integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint learner_personalization_signals_unique unique (user_id, language_code, kind, code),
  constraint learner_personalization_signals_count_check check (usage_count >= 1),
  constraint learner_personalization_signals_code_check check (
    (kind = 'topic' and code in (
      'travel', 'food', 'technology', 'work_career', 'school', 'sports', 'music', 'movies', 'games',
      'books', 'news', 'shopping', 'nature', 'art', 'daily_life', 'culture', 'business'))
    or (kind = 'goal' and code in (
      'travel', 'work', 'study_abroad', 'exam', 'conversation', 'watching_media', 'reading', 'hobby'))
    or (kind = 'error_type' and code in (
      'verb_tense', 'subject_verb_agreement', 'articles', 'prepositions', 'word_order', 'plural_forms',
      'pronouns', 'conjunctions', 'word_choice', 'measure_words', 'aspect_particles', 'complements'))
    or (kind = 'pace' and code in ('slow', 'steady', 'fast'))
    or (kind = 'turn_length' and code in ('short', 'medium', 'long')))
);

comment on table v3.learner_personalization_signals is
  'FR-3.6: structured, closed-code signals that tune the agent to a learner. Never read by grading, the usage ladder, review or progression.';

create index if not exists learner_personalization_signals_user_idx
  on v3.learner_personalization_signals (user_id, language_code, updated_at desc);

alter table v3.learner_agent_consent enable row level security;
alter table v3.learner_personalization_signals enable row level security;

revoke all privileges on v3.learner_agent_consent from anon, authenticated;
revoke all privileges on v3.learner_personalization_signals from anon, authenticated;
grant select on v3.learner_agent_consent to authenticated;
grant select on v3.learner_personalization_signals to authenticated;
grant all privileges on v3.learner_agent_consent to service_role;
grant all privileges on v3.learner_personalization_signals to service_role;

drop policy if exists "Users can read own agent consent" on v3.learner_agent_consent;
create policy "Users can read own agent consent"
  on v3.learner_agent_consent for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own personalization signals" on v3.learner_personalization_signals;
create policy "Users can read own personalization signals"
  on v3.learner_personalization_signals for select
  to authenticated
  using ((select auth.uid()) = user_id);
