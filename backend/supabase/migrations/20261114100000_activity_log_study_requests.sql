-- Restructure phase 1 (docs/architecture/TARGET_DESIGN.md section 4, PRD 8.10): one lasting learning log and the
-- study requests the agent or the system gives the learner.
--   * learner_activity_log: one row per thing the learner did, in the language it was done in. Rows are only added;
--     a retried request carries the same client_event_id and is stored once. Kept until the learner deletes it or
--     the account (cascade). No audio and no long text: detail is a small object.
--   * learner_study_requests: work for the learner; closed automatically when a correct log row for the same item
--     arrives, or dismissed by the learner.
--   * learner_practice_events no longer expires after 90 days: new rows get no expiry and rows still inside their
--     90 days keep their data; the hourly purge stops deleting them. The table stays until a later phase.
-- Both new tables are backend-only: row security on, no grant to anon or authenticated, service role only.
-- Additive and forward-only. Applying it to any environment needs the owner's approval for that environment.

create table if not exists v3.learner_activity_log (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  client_event_id text not null,
  kind text not null,
  item_type text,
  item_id text,
  source_type text,
  source_id text,
  outcome text not null,
  score numeric(4,1),
  detail jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  constraint learner_activity_log_event_unique unique (user_id, client_event_id),
  constraint learner_activity_log_event_check check (char_length(client_event_id) between 1 and 200),
  constraint learner_activity_log_kind_check check (kind in (
    'video_watched', 'lookup', 'word_saved', 'dictation', 'shadowing', 'region_question', 'flashcard', 'choice',
    'cloze', 'listening', 'pronunciation', 'writing', 'grammar_lesson', 'grammar_exercise', 'speaking_turn',
    'speaking_session', 'roleplay')),
  constraint learner_activity_log_item_check check (
    (item_type is null and item_id is null)
    or (item_type in ('concept', 'grammar_point', 'segment', 'region') and char_length(item_id) between 1 and 200)),
  constraint learner_activity_log_source_check check (
    (source_type is null and source_id is null)
    or (source_type in ('video_region', 'notebook', 'review_deck', 'agent_session')
        and (source_id is null or char_length(source_id) between 1 and 200))),
  constraint learner_activity_log_outcome_check check (outcome in ('correct', 'incorrect', 'partial', 'done')),
  constraint learner_activity_log_score_check check (score is null or score between 0 and 100),
  constraint learner_activity_log_detail_check check (
    jsonb_typeof(detail) = 'object' and pg_column_size(detail) <= 2048)
);

comment on table v3.learner_activity_log is
  'Restructure phase 1: the learner''s lasting learning log, append-only, idempotent by (user_id, client_event_id). Read by Progress, Home and the agent through the backend only.';

create index if not exists learner_activity_log_recent_idx
  on v3.learner_activity_log (user_id, language_code, occurred_at desc);

alter table v3.learner_activity_log enable row level security;
revoke all privileges on v3.learner_activity_log from public, anon, authenticated;
grant all privileges on v3.learner_activity_log to service_role;

create table if not exists v3.learner_study_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  kind text not null,
  item_type text not null,
  item_id text not null,
  reason text,
  status text not null default 'open',
  created_by text not null,
  created_at timestamptz not null default now(),
  closed_at timestamptz,
  constraint learner_study_requests_kind_check check (
    (kind = 'grammar_redo' and item_type = 'grammar_point')
    or (kind in ('word_review', 'pronunciation_retry') and item_type = 'concept')
    or (kind = 'region_practice' and item_type = 'region')),
  constraint learner_study_requests_item_check check (char_length(item_id) between 1 and 200),
  constraint learner_study_requests_reason_check check (reason is null or char_length(reason) <= 300),
  constraint learner_study_requests_status_check check (status in ('open', 'done', 'dismissed')),
  constraint learner_study_requests_creator_check check (created_by in ('agent', 'system')),
  constraint learner_study_requests_closed_check check ((status = 'open') = (closed_at is null))
);

comment on table v3.learner_study_requests is
  'Restructure phase 1: study work the agent or the system gives the learner. Closes itself when a correct log row for the same item arrives. Backend-only.';

create index if not exists learner_study_requests_list_idx
  on v3.learner_study_requests (user_id, language_code, status, created_at desc);
create index if not exists learner_study_requests_open_item_idx
  on v3.learner_study_requests (user_id, item_type, item_id) where status = 'open';

alter table v3.learner_study_requests enable row level security;
revoke all privileges on v3.learner_study_requests from public, anon, authenticated;
grant all privileges on v3.learner_study_requests to service_role;

-- The practice log is kept until the learner deletes it or the account: no more 90-day expiry.
alter table v3.learner_practice_events alter column expires_at set default 'infinity'::timestamptz;
update v3.learner_practice_events set expires_at = 'infinity'::timestamptz
  where expires_at > now() and expires_at <> 'infinity'::timestamptz;

-- The hourly purge no longer touches the practice log (the 'practice_events' count is gone from its result).
create or replace function v3.purge_expired_learner_data(p_limit integer default 1000)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare lookups integer; transcripts integer; scores integer;
begin
  if p_limit is null or p_limit < 1 or p_limit > 10000 then
    raise exception 'Invalid purge limit' using errcode = '22023';
  end if;
  delete from v3.learner_looked_up_concepts where (user_id, concept_id) in (
    select user_id, concept_id from v3.learner_looked_up_concepts where expires_at <= now() limit p_limit);
  get diagnostics lookups = row_count;
  delete from v3.learner_speech_transcripts where id in (
    select id from v3.learner_speech_transcripts where occurred_at <= now() - interval '12 months' limit p_limit);
  get diagnostics transcripts = row_count;
  delete from v3.learner_pronunciation_scores where id in (
    select id from v3.learner_pronunciation_scores where occurred_at <= now() - interval '12 months' limit p_limit);
  get diagnostics scores = row_count;
  return jsonb_build_object('looked_up', lookups, 'speech_transcripts', transcripts, 'pronunciation_scores', scores);
end $$;

revoke all on function v3.purge_expired_learner_data(integer) from public, anon, authenticated;
grant execute on function v3.purge_expired_learner_data(integer) to service_role;
