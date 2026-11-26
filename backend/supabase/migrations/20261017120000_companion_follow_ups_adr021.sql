-- ADR-021 G4: proposals the companion adds to today's plan when a conversation ends.
--
-- A conversation can end with up to two follow-up proposals (review what is due, practise the video
-- the learner talked about). They join the learner's existing plan for that day as ordinary
-- `companion_proposals` rows, so Home and the conversation show the same items and the same
-- accept/dismiss endpoints apply. This function only appends rows; it never changes learner state.
-- Service role only. Forward-only.

create or replace function v3.append_companion_proposals(
  p_user_id uuid,
  p_plan_id uuid,
  p_items jsonb
)
returns setof uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_item jsonb;
  v_position integer;
  v_id uuid;
begin
  if p_items is null or jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) > 2 then
    raise exception 'companion_plan_conflict: invalid_items';
  end if;

  -- The plan must belong to the learner; lock it so concurrent appends get distinct positions.
  perform 1 from v3.companion_plans where id = p_plan_id and user_id = p_user_id for update;
  if not found then
    raise exception 'companion_plan_conflict: plan_not_found';
  end if;

  select coalesce(max(position), -1) + 1 into v_position
  from v3.companion_proposals where plan_id = p_plan_id;

  for v_item in select value from jsonb_array_elements(p_items) loop
    if v_position > 9 then
      exit;  -- a day's plan holds at most ten proposals; extra follow-ups are dropped
    end if;
    -- Skip a proposal the plan already holds for the same kind and target.
    if exists (
      select 1 from v3.companion_proposals
      where plan_id = p_plan_id and kind = v_item->>'kind'
        and library_item_id is not distinct from nullif(v_item->>'library_item_id', '')::uuid
        and companion_entry is not distinct from v_item->>'companion_entry'
    ) then
      continue;
    end if;
    insert into v3.companion_proposals (
      plan_id, user_id, position, kind, library_item_id, video_title, companion_entry, item_count,
      minutes, reason)
    values (
      p_plan_id, p_user_id, v_position, v_item->>'kind', nullif(v_item->>'library_item_id', '')::uuid,
      v_item->>'video_title', v_item->>'companion_entry', (v_item->>'item_count')::integer,
      (v_item->>'minutes')::smallint, v_item->>'reason')
    returning id into v_id;
    v_position := v_position + 1;
    return next v_id;
  end loop;
end;
$$;

revoke all on function v3.append_companion_proposals(uuid, uuid, jsonb) from public, anon, authenticated;
grant execute on function v3.append_companion_proposals(uuid, uuid, jsonb) to service_role;
