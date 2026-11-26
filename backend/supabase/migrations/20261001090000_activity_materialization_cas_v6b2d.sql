-- 6B-2D / A09. PREPARED ONLY; owner authorization required before hosted apply.
-- Existing activity UUID is the execution identity. No backfill or regeneration.
begin;

create function v3.guard_materialized_activity_payload()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if old.prompt_payload <> '{}'::jsonb or old.expected_response_payload is not null then
    if new.prompt_payload is distinct from old.prompt_payload
       or new.expected_response_payload is distinct from old.expected_response_payload
       or new.id is distinct from old.id
       or new.session_id is distinct from old.session_id
       or new.activity_type is distinct from old.activity_type
       or new.concept_id is distinct from old.concept_id
       or new.learning_object_id is distinct from old.learning_object_id
       or new.position is distinct from old.position
       or new.review_origin is distinct from old.review_origin
       or new.review_mode is distinct from old.review_mode
       or new.review_state_id is distinct from old.review_state_id
       or new.review_provenance_version is distinct from old.review_provenance_version
       or new.source_review_state_version is distinct from old.source_review_state_version then
      raise exception 'activity_materialization_conflict: immutable_payload_or_identity' using errcode = '23514';
    end if;
  end if;
  return new;
end;
$$;

create trigger session_activity_materialization_immutable
before update on v3.session_activities
for each row execute function v3.guard_materialized_activity_payload();

create function v3.materialize_session_activity_if_absent(
  p_user_id uuid, p_session_activity_id uuid,
  p_prompt_payload jsonb, p_expected_response_payload jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_activity v3.session_activities;
  v_installed boolean := false;
begin
  if p_user_id is null or p_session_activity_id is null then
    raise exception 'activity_materialization_conflict: missing_identity';
  end if;
  if not exists (
    select 1 from v3.session_activities a
    join v3.learning_sessions s on s.id = a.session_id
    where a.id = p_session_activity_id and s.user_id = p_user_id
  ) then
    raise exception 'activity_materialization_conflict: activity_not_found';
  end if;
  if p_prompt_payload is null or jsonb_typeof(p_prompt_payload) <> 'object'
     or p_prompt_payload = '{}'::jsonb
     or jsonb_typeof(p_prompt_payload->'_materialization') is distinct from 'object'
     or jsonb_typeof(p_prompt_payload#>'{_materialization,provenance}') is distinct from 'object'
     or (p_expected_response_payload is not null and jsonb_typeof(p_expected_response_payload) <> 'object') then
    raise exception 'activity_materialization_conflict: invalid_payload';
  end if;

  -- UPDATE locks only for the final write. PostgreSQL rechecks the absence
  -- predicate after a concurrent writer commits. All generation is outside SQL.
  update v3.session_activities a
  set prompt_payload = p_prompt_payload,
      expected_response_payload = p_expected_response_payload,
      status = 'active', updated_at = now()
  where a.id = p_session_activity_id
    and a.prompt_payload = '{}'::jsonb and a.expected_response_payload is null
    and a.status in ('planned', 'active')
    and p_prompt_payload->>'activity_kind' = a.activity_type::text
    and p_prompt_payload#>>'{_materialization,provenance,source_learning_object_id}' = a.learning_object_id::text
    and p_prompt_payload#>>'{_materialization,provenance,source_concept_id}' = a.concept_id::text
    and exists (
      select 1 from v3.learning_sessions s
      join v3.learning_objects lo on lo.id = a.learning_object_id
      where s.id = a.session_id and s.user_id = p_user_id
        and lo.concept_id = a.concept_id
        and lo.transcript_segment_id::text = p_prompt_payload#>>'{_materialization,provenance,source_transcript_segment_id}'
        and lower(s.language_code) = lower(p_prompt_payload#>>'{_materialization,provenance,language_code}')
    )
  returning a.* into v_activity;
  v_installed := found;

  if not v_installed then
    -- A new READ COMMITTED statement sees the winner, not the loser's candidate.
    select a.* into v_activity from v3.session_activities a
    join v3.learning_sessions s on s.id = a.session_id
    where a.id = p_session_activity_id and s.user_id = p_user_id;
    if not found or v_activity.prompt_payload = '{}'::jsonb then
      raise exception 'activity_materialization_conflict: not_materializable';
    end if;
  end if;
  return jsonb_build_object('installed', v_installed, 'activity', to_jsonb(v_activity));
end;
$$;

-- Failure must not poison the gap between canonical commit and activation.
-- Lock order matches materialize -> mark_active: activity first, reservation next.
create or replace function v3.mark_review_materialization_failed(
  p_materialization_id uuid, p_user_id uuid, p_session_activity_id uuid, p_reason text
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_activity v3.session_activities;
  v_materialization v3.review_materializations;
begin
  select a.* into v_activity from v3.session_activities a
  join v3.learning_sessions s on s.id = a.session_id
  where a.id = p_session_activity_id and s.user_id = p_user_id
  for update of a;
  if not found then
    raise exception 'review_materialization_conflict: activity_not_found';
  end if;
  update v3.review_materializations
  set status = case when status = 'active' then status
                    when v_activity.prompt_payload <> '{}'::jsonb or v_activity.expected_response_payload is not null then status
                    else 'failed' end,
      updated_at = now(),
      metadata = case when status = 'active' or v_activity.prompt_payload <> '{}'::jsonb
                          or v_activity.expected_response_payload is not null then metadata
                      else metadata || jsonb_build_object('last_failure_reason', left(coalesce(p_reason, ''), 500)) end
  where id = p_materialization_id and user_id = p_user_id
    and session_activity_id = p_session_activity_id and learning_session_id = v_activity.session_id
  returning * into v_materialization;
  if not found then
    raise exception 'review_materialization_conflict: materialization_not_found';
  end if;
  return v3.review_materialization_result(v_materialization, false);
end;
$$;

revoke all on function v3.guard_materialized_activity_payload() from public, anon, authenticated;
revoke all on function v3.materialize_session_activity_if_absent(uuid, uuid, jsonb, jsonb) from public, anon, authenticated;
revoke all on function v3.mark_review_materialization_failed(uuid, uuid, uuid, text) from public, anon, authenticated;
grant execute on function v3.guard_materialized_activity_payload() to service_role;
grant execute on function v3.materialize_session_activity_if_absent(uuid, uuid, jsonb, jsonb) to service_role;
grant execute on function v3.mark_review_materialization_failed(uuid, uuid, uuid, text) to service_role;

comment on function v3.materialize_session_activity_if_absent(uuid, uuid, jsonb, jsonb) is
  'Backend-only final-write CAS; validated proposals only; canonical first winner returned. No LLM, grading or learner-state effects.';
commit;
