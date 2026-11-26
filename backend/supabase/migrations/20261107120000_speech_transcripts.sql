-- PRD FR-3.11 / Q18 (decided 2026-11-07): with a second, separate consent the learner's spoken turns are kept as
-- text for level calibration and for the learner's own review. No audio. Kept 12 months from the turn, then purged.
-- The consent is default off (null = never asked) and counts only while the voice consent (FR-3.4) is granted too;
-- the server checks both before it stores anything. Backend-only: no grant to anon or authenticated, the learner
-- reads, exports and deletes through authenticated FastAPI routes. Rows cascade with the account.
-- Forward-only. Applying it to any environment needs the owner's approval for that environment.

alter table v3.learner_agent_consent
  add column if not exists transcript_consent boolean,
  add column if not exists transcript_decided_at timestamptz;

comment on column v3.learner_agent_consent.transcript_consent is
  'FR-3.11: null = never asked, true = keep transcripts for calibration and review, false = revoked. Effective only with voice_consent = true.';

create table if not exists v3.learner_speech_transcripts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  -- One voice conversation; turn_index orders its learner turns.
  session_id uuid not null,
  turn_index integer not null,
  language_code text not null references v3.languages(code) on delete restrict,
  library_item_id uuid,
  topic text,
  -- The help ladder step the learner had reached before this turn (0 = none, 3 = model answer shown).
  assistance_level smallint not null default 0,
  agent_text text,
  learner_text text not null,
  -- Azure's recognition of the same turn, and its per-word scores, when the turn was scored.
  recognized_text text,
  word_scores jsonb not null default '[]'::jsonb,
  -- Corrections shown for this turn: quote, suggestion, note and error type; learner_text is the original sentence.
  grammar_errors jsonb not null default '[]'::jsonb,
  occurred_at timestamptz not null,
  created_at timestamptz not null default now(),
  constraint learner_speech_transcripts_turn_unique unique (user_id, session_id, turn_index),
  constraint learner_speech_transcripts_turn_check check (turn_index between 0 and 199),
  constraint learner_speech_transcripts_assistance_check check (assistance_level between 0 and 3),
  constraint learner_speech_transcripts_text_check check (
    char_length(learner_text) between 1 and 2000
    and (agent_text is null or char_length(agent_text) <= 2000)
    and (recognized_text is null or char_length(recognized_text) <= 2000)
    and (topic is null or char_length(topic) <= 200)),
  constraint learner_speech_transcripts_json_check check (
    jsonb_typeof(word_scores) = 'array' and jsonb_typeof(grammar_errors) = 'array')
);

comment on table v3.learner_speech_transcripts is
  'FR-3.11: the learner''s spoken turns as text, kept only with the separate transcript consent, for calibration and review. No audio. Purged 12 months after occurred_at. Never logged; backend-only.';

create index if not exists learner_speech_transcripts_user_idx
  on v3.learner_speech_transcripts (user_id, occurred_at desc);
create index if not exists learner_speech_transcripts_occurred_idx
  on v3.learner_speech_transcripts (occurred_at);

alter table v3.learner_speech_transcripts enable row level security;
revoke all privileges on v3.learner_speech_transcripts from public, anon, authenticated;
grant all privileges on v3.learner_speech_transcripts to service_role;

-- The hourly retention purge also removes transcripts older than 12 months.
create or replace function v3.purge_expired_learner_data(p_limit integer default 1000)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare practice integer; lookups integer; transcripts integer;
begin
  if p_limit is null or p_limit < 1 or p_limit > 10000 then
    raise exception 'Invalid purge limit' using errcode = '22023';
  end if;
  delete from v3.learner_practice_events where id in (
    select id from v3.learner_practice_events where expires_at <= now() limit p_limit);
  get diagnostics practice = row_count;
  delete from v3.learner_looked_up_concepts where (user_id, concept_id) in (
    select user_id, concept_id from v3.learner_looked_up_concepts where expires_at <= now() limit p_limit);
  get diagnostics lookups = row_count;
  delete from v3.learner_speech_transcripts where id in (
    select id from v3.learner_speech_transcripts where occurred_at <= now() - interval '12 months' limit p_limit);
  get diagnostics transcripts = row_count;
  return jsonb_build_object('practice_events', practice, 'looked_up', lookups, 'speech_transcripts', transcripts);
end $$;

revoke all on function v3.purge_expired_learner_data(integer) from public, anon, authenticated;
grant execute on function v3.purge_expired_learner_data(integer) to service_role;
