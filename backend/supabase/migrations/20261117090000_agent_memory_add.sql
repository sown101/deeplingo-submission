-- Adding an agent memory row and trimming the learner's oldest rows in one transaction (PRD 8.12 point 3).
--
-- The backend used to read the learner's rows, delete the surplus and insert the new row as three separate requests:
-- a failed insert after the delete lost an old row, and two conversations adding at once could both pass the cap of
-- 40. This function inserts first, then removes everything older than the newest `p_max_rows`, under a per-learner
-- advisory lock, so it either happens whole or not at all. `learner_agent_memory` itself is unchanged.
-- Backend-only: the service role may call it, nobody else.

create or replace function v3.add_agent_memory(p_user_id uuid, p_kind text, p_text text, p_language_code text,
                                               p_max_rows integer)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_id uuid;
begin
  perform pg_advisory_xact_lock(hashtextextended('learner_agent_memory:' || p_user_id::text, 0));
  insert into v3.learner_agent_memory (user_id, kind, text, language_code, created_at)
  values (p_user_id, p_kind, p_text, p_language_code, clock_timestamp())
  returning id into v_id;
  delete from v3.learner_agent_memory m
   where m.user_id = p_user_id
     and m.id in (select r.id from v3.learner_agent_memory r
                   where r.user_id = p_user_id
                   order by r.created_at desc, r.id desc
                   offset greatest(p_max_rows, 1));
  return v_id;
end;
$$;

revoke all on function v3.add_agent_memory(uuid, text, text, text, integer) from public, anon, authenticated;
grant execute on function v3.add_agent_memory(uuid, text, text, text, integer) to service_role;
