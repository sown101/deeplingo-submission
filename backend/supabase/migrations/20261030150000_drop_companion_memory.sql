-- PRD FR-3.6: the free-text companion memory is replaced by closed-code personalization signals
-- (20261029120000_agent_consent_signals.sql). Run this only after the code that no longer reads or
-- writes the old tables is deployed. Forward-only; the notes it holds are not carried over.
-- Applying it to any environment needs the owner's approval for that environment.

-- The retention purge no longer touches the memory table.
create or replace function v3.purge_expired_learner_data(p_limit integer default 1000)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare practice integer; lookups integer;
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
  return jsonb_build_object('practice_events', practice, 'looked_up', lookups);
end $$;

drop table if exists v3.learner_companion_memory;
drop table if exists v3.learner_companion_settings;
