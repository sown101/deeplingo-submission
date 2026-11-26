-- DeepLingo v3 migration 033: learner-facing review session orchestration.

alter table v3.session_activities
  add column if not exists review_origin boolean not null default false,
  add column if not exists review_mode v3.review_mode,
  add column if not exists review_state_id uuid references v3.review_states(id) on delete set null,
  add column if not exists source_review_state_version integer,
  add column if not exists review_provenance_version text;

alter table v3.session_activities
  add constraint session_activities_review_provenance_chk check (
    (
      review_origin = false
      and review_mode is null
      and review_state_id is null
      and source_review_state_version is null
      and review_provenance_version is null
    )
    or
    (
      review_origin = true
      and review_mode is not null
      and review_state_id is not null
      and source_review_state_version is not null
      and source_review_state_version >= 0
      and review_provenance_version is not null
    )
  );

create index if not exists session_activities_review_provenance_idx
  on v3.session_activities (review_origin, review_mode, review_state_id, source_review_state_version);

create unique index if not exists learning_sessions_one_active_5h_review_session_idx
  on v3.learning_sessions (user_id, language_code)
  where type = 'review'
    and status in ('planned', 'active')
    and goal->>'session_policy_version' = '5h1-review-session-orchestration';

create or replace function v3.start_or_resume_review_session(
  p_user_id uuid,
  p_language_code text,
  p_goal jsonb,
  p_max_items integer
)
returns jsonb
language plpgsql
security invoker
set search_path = v3, extensions
as $$
declare
  v_session v3.learning_sessions;
  v_goal jsonb := coalesce(p_goal, '{}'::jsonb)
    || jsonb_build_object(
      'origin', 'review',
      'session_policy_version', '5h1-review-session-orchestration',
      'max_items', p_max_items,
      'target_language_code', p_language_code
    );
begin
  if p_max_items < 1 or p_max_items > 50 then
    raise exception 'review_session_conflict: invalid_max_items';
  end if;

  select *
    into v_session
  from v3.learning_sessions
  where user_id = p_user_id
    and language_code = p_language_code
    and type = 'review'
    and status in ('planned', 'active')
    and goal->>'session_policy_version' = '5h1-review-session-orchestration'
  order by created_at
  limit 1;

  if v_session.id is not null then
    return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
  end if;

  insert into v3.learning_sessions (
    user_id,
    language_code,
    type,
    status,
    goal
  )
  values (
    p_user_id,
    p_language_code,
    'review',
    'active',
    v_goal
  )
  returning * into v_session;

  return jsonb_build_object('created', true, 'session', to_jsonb(v_session));
exception
  when unique_violation then
    select *
      into v_session
    from v3.learning_sessions
    where user_id = p_user_id
      and language_code = p_language_code
      and type = 'review'
      and status in ('planned', 'active')
      and goal->>'session_policy_version' = '5h1-review-session-orchestration'
    order by created_at
    limit 1;

    if v_session.id is not null then
      return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
    end if;
    raise;
end;
$$;

create or replace function v3.reserve_review_materialization(p_payload jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = v3, extensions
as $$
declare
  v_user_id uuid := (p_payload->>'user_id')::uuid;
  v_language_code text := p_payload->>'language_code';
  v_concept_id uuid := (p_payload->>'concept_id')::uuid;
  v_review_mode v3.review_mode := (p_payload->>'review_mode')::v3.review_mode;
  v_review_state_id uuid := (p_payload->>'review_state_id')::uuid;
  v_source_review_state_version integer := (p_payload->>'source_review_state_version')::integer;
  v_activity_type v3.activity_type := (p_payload->>'activity_type')::v3.activity_type;
  v_learning_object_id uuid := (p_payload->>'learning_object_id')::uuid;
  v_transcript_segment_id uuid := (p_payload->>'transcript_segment_id')::uuid;
  v_goal jsonb := coalesce(p_payload->'goal', '{}'::jsonb);
  v_requested_session_id uuid := nullif(p_payload->>'learning_session_id', '')::uuid;
  v_position integer := coalesce((p_payload->>'position')::integer, 1);
  v_session_id uuid;
  v_activity_id uuid;
  v_materialization v3.review_materializations;
begin
  select *
    into v_materialization
  from v3.review_materializations
  where user_id = v_user_id
    and concept_id = v_concept_id
    and review_mode = v_review_mode
    and review_state_id = v_review_state_id
    and source_review_state_version = v_source_review_state_version
  limit 1;

  if v_materialization.id is not null then
    return v3.review_materialization_result(v_materialization, false);
  end if;

  if v_position < 1 then
    raise exception 'review_materialization_conflict: invalid_position';
  end if;

  if not exists (
    select 1
    from v3.review_states rs
    where rs.id = v_review_state_id
      and rs.user_id = v_user_id
      and rs.concept_id = v_concept_id
      and rs.review_mode = v_review_mode
      and rs.version = v_source_review_state_version
  ) then
    raise exception 'review_materialization_conflict: review_state_identity';
  end if;

  if not exists (
    select 1
    from v3.concepts c
    where c.id = v_concept_id
      and c.language_code = v_language_code
  ) then
    raise exception 'review_materialization_conflict: concept_language';
  end if;

  if not exists (
    select 1
    from v3.learning_objects lo
    where lo.id = v_learning_object_id
      and lo.concept_id = v_concept_id
      and lo.transcript_segment_id = v_transcript_segment_id
  ) then
    raise exception 'review_materialization_conflict: learning_object_identity';
  end if;

  if v_requested_session_id is not null then
    if not exists (
      select 1
      from v3.learning_sessions s
      where s.id = v_requested_session_id
        and s.user_id = v_user_id
        and s.language_code = v_language_code
        and s.type = 'review'
        and s.status in ('planned', 'active')
    ) then
      raise exception 'review_materialization_conflict: session_identity';
    end if;
    v_session_id := v_requested_session_id;
  else
    insert into v3.learning_sessions (
      user_id,
      language_code,
      type,
      status,
      goal,
      time_budget_seconds
    )
    values (
      v_user_id,
      v_language_code,
      'review',
      'planned',
      v_goal,
      null
    )
    returning id into v_session_id;
  end if;

  insert into v3.session_activities (
    session_id,
    concept_id,
    learning_object_id,
    activity_type,
    position,
    review_origin,
    review_mode,
    review_state_id,
    source_review_state_version,
    review_provenance_version,
    prompt_payload,
    expected_response_payload,
    status
  )
  values (
    v_session_id,
    v_concept_id,
    v_learning_object_id,
    v_activity_type,
    v_position,
    true,
    v_review_mode,
    v_review_state_id,
    v_source_review_state_version,
    'review-provenance-v3-activity',
    '{}'::jsonb,
    null,
    'planned'
  )
  returning id into v_activity_id;

  insert into v3.review_materializations (
    user_id,
    concept_id,
    review_mode,
    review_state_id,
    source_review_state_version,
    learning_session_id,
    session_activity_id,
    activity_type,
    status,
    metadata
  )
  values (
    v_user_id,
    v_concept_id,
    v_review_mode,
    v_review_state_id,
    v_source_review_state_version,
    v_session_id,
    v_activity_id,
    v_activity_type,
    'reserved',
    jsonb_build_object(
      'reservation_version', 'review-materialization-reservation-v2',
      'source_review_state_version', v_source_review_state_version,
      'activity_review_provenance', 'session_activities'
    )
  )
  returning * into v_materialization;

  return v3.review_materialization_result(v_materialization, true);
exception
  when unique_violation then
    select *
      into v_materialization
    from v3.review_materializations
    where user_id = v_user_id
      and concept_id = v_concept_id
      and review_mode = v_review_mode
      and review_state_id = v_review_state_id
      and source_review_state_version = v_source_review_state_version
    limit 1;

    if v_materialization.id is not null then
      return v3.review_materialization_result(v_materialization, false);
    end if;
    raise;
end;
$$;

create or replace function v3.mark_review_materialization_active(
  p_materialization_id uuid,
  p_user_id uuid,
  p_session_activity_id uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = v3, extensions
as $$
declare
  v_materialization v3.review_materializations;
begin
  if not exists (
    select 1
    from v3.review_materializations rm
    join v3.learning_sessions s on s.id = rm.learning_session_id
    join v3.session_activities a on a.id = rm.session_activity_id
    where rm.id = p_materialization_id
      and rm.user_id = p_user_id
      and rm.session_activity_id = p_session_activity_id
      and s.user_id = p_user_id
      and a.session_id = s.id
      and a.id = p_session_activity_id
      and a.concept_id = rm.concept_id
      and a.activity_type = rm.activity_type
      and a.review_origin = true
      and a.review_mode = rm.review_mode
      and a.review_state_id = rm.review_state_id
      and a.source_review_state_version = rm.source_review_state_version
      and a.status = 'active'
      and a.prompt_payload <> '{}'::jsonb
  ) then
    raise exception 'review_materialization_conflict: activity_not_active';
  end if;

  update v3.review_materializations
  set status = 'active',
      updated_at = now(),
      metadata = metadata || jsonb_build_object('activated_at', now())
  where id = p_materialization_id
    and user_id = p_user_id
    and session_activity_id = p_session_activity_id
  returning * into v_materialization;

  if v_materialization.id is null then
    raise exception 'review_materialization_conflict: materialization_not_found';
  end if;

  return v3.review_materialization_result(v_materialization, false);
end;
$$;

revoke all on function v3.start_or_resume_review_session(uuid, text, jsonb, integer) from public;
revoke all on function v3.reserve_review_materialization(jsonb) from public;
revoke all on function v3.mark_review_materialization_active(uuid, uuid, uuid) from public;

grant execute on function v3.start_or_resume_review_session(uuid, text, jsonb, integer) to service_role;
grant execute on function v3.reserve_review_materialization(jsonb) to service_role;
grant execute on function v3.mark_review_materialization_active(uuid, uuid, uuid) to service_role;

comment on column v3.session_activities.review_origin is
  'Activity-level authority that this SessionActivity originated from the adaptive review pipeline.';
comment on column v3.session_activities.review_mode is
  'Authoritative ReviewMode for review-origin activities. Required for multi-activity review sessions.';
comment on column v3.session_activities.review_state_id is
  'ReviewState identity used when reserving this review activity.';
comment on column v3.session_activities.source_review_state_version is
  'ReviewState version used as provenance for this materialized review opportunity.';
comment on function v3.start_or_resume_review_session(uuid, text, jsonb, integer) is
  'Atomic start/resume boundary for one active 5H review session per user and language.';
