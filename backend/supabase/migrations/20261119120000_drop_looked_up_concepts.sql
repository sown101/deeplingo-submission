-- Drop the looked-up words table and its write function. WRITTEN, NOT APPLIED to any environment.
--
-- APPLY ONLY AFTER the backend that no longer writes this table is deployed: the previous backend still calls
-- v3.record_looked_up_concept on every workspace and agent lookup, and its hourly purge still reads the result key
-- `looked_up`. Lookups are in v3.learner_activity_log (kind 'lookup'); nothing reads this table any more (the Quick
-- review function that did was dropped by 20261116091000, and the data export no longer lists it).
--
-- The hourly purge function named the table, so it is replaced first, without the looked-up step; its other two
-- steps are unchanged from 20261114100000.

create or replace function v3.purge_expired_learner_data(p_limit integer default 1000)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare transcripts integer; scores integer;
begin
  if p_limit is null or p_limit < 1 or p_limit > 10000 then
    raise exception 'Invalid purge limit' using errcode = '22023';
  end if;
  delete from v3.learner_speech_transcripts where id in (
    select id from v3.learner_speech_transcripts where occurred_at <= now() - interval '12 months' limit p_limit);
  get diagnostics transcripts = row_count;
  delete from v3.learner_pronunciation_scores where id in (
    select id from v3.learner_pronunciation_scores where occurred_at <= now() - interval '12 months' limit p_limit);
  get diagnostics scores = row_count;
  return jsonb_build_object('speech_transcripts', transcripts, 'pronunciation_scores', scores);
end $$;

revoke all on function v3.purge_expired_learner_data(integer) from public, anon, authenticated;
grant execute on function v3.purge_expired_learner_data(integer) to service_role;

drop function if exists v3.record_looked_up_concept(uuid, uuid, text);
drop table if exists v3.learner_looked_up_concepts;
