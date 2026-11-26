-- Owner decision 2026-11-08: keep the average Azure scores and weak words of each consented speaking practice for the
-- Progress tab. No audio and no sentence. Backend-only; rows cascade with the account and expire after 12 months.
-- Forward-only. Applying it to any environment needs the owner's approval for that environment.

create table if not exists v3.learner_pronunciation_scores (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  source text not null check (source in ('conversation', 'shadowing', 'jam')),
  pronunciation numeric(5,1) not null check (pronunciation between 0 and 100),
  accuracy numeric(5,1) not null check (accuracy between 0 and 100),
  fluency numeric(5,1) not null check (fluency between 0 and 100),
  weak_words jsonb not null default '[]'::jsonb check (jsonb_typeof(weak_words) = 'array'),
  occurred_at timestamptz not null default now()
);
create index if not exists learner_pronunciation_scores_user_idx
  on v3.learner_pronunciation_scores (user_id, language_code, occurred_at);

alter table v3.learner_pronunciation_scores enable row level security;
revoke all privileges on v3.learner_pronunciation_scores from public, anon, authenticated;
grant all privileges on v3.learner_pronunciation_scores to service_role;

create or replace function v3.purge_expired_learner_data(p_limit integer default 1000)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare practice integer; lookups integer; transcripts integer; scores integer;
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
  delete from v3.learner_pronunciation_scores where id in (
    select id from v3.learner_pronunciation_scores where occurred_at <= now() - interval '12 months' limit p_limit);
  get diagnostics scores = row_count;
  return jsonb_build_object('practice_events', practice, 'looked_up', lookups, 'speech_transcripts', transcripts,
                            'pronunciation_scores', scores);
end $$;

revoke all on function v3.purge_expired_learner_data(integer) from public, anon, authenticated;
grant execute on function v3.purge_expired_learner_data(integer) to service_role;
