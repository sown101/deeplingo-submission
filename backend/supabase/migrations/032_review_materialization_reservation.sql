-- DeepLingo v3 migration 032: review materialization reservation and idempotency.

create table if not exists v3.review_materializations (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  review_mode v3.review_mode not null,
  review_state_id uuid not null references v3.review_states(id) on delete cascade,
  source_review_state_version integer not null,
  learning_session_id uuid not null references v3.learning_sessions(id) on delete cascade,
  session_activity_id uuid not null references v3.session_activities(id) on delete cascade,
  activity_type v3.activity_type not null,
  status text not null default 'reserved',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint review_materializations_opportunity_unique unique (
    user_id,
    concept_id,
    review_mode,
    review_state_id,
    source_review_state_version
  ),
  constraint review_materializations_session_unique unique (learning_session_id),
  constraint review_materializations_activity_unique unique (session_activity_id),
  constraint review_materializations_status_chk check (status in ('reserved', 'active', 'failed')),
  constraint review_materializations_version_chk check (source_review_state_version >= 0),
  constraint review_materializations_metadata_object_chk check (jsonb_typeof(metadata) = 'object')
);

create index if not exists review_materializations_user_status_idx
  on v3.review_materializations (user_id, status, created_at desc);

create index if not exists review_materializations_review_state_idx
  on v3.review_materializations (review_state_id, source_review_state_version);

alter table v3.review_materializations enable row level security;

grant select on v3.review_materializations to authenticated;
grant all privileges on v3.review_materializations to service_role;

create policy "Users can read own review materializations"
  on v3.review_materializations for select
  to authenticated
  using ((select auth.uid()) = user_id);

create or replace function v3.review_materialization_result(
  p_row v3.review_materializations,
  p_created boolean
)
returns jsonb
language sql
stable
security invoker
set search_path = v3, extensions
as $$
  select jsonb_build_object(
    'materialization_id', p_row.id,
    'user_id', p_row.user_id,
    'concept_id', p_row.concept_id,
    'review_mode', p_row.review_mode,
    'review_state_id', p_row.review_state_id,
    'source_review_state_version', p_row.source_review_state_version,
    'learning_session_id', p_row.learning_session_id,
    'session_activity_id', p_row.session_activity_id,
    'activity_type', p_row.activity_type,
    'status', p_row.status,
    'created', p_created,
    'metadata', p_row.metadata,
    'created_at', p_row.created_at,
    'updated_at', p_row.updated_at
  );
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

  insert into v3.session_activities (
    session_id,
    concept_id,
    learning_object_id,
    activity_type,
    position,
    prompt_payload,
    expected_response_payload,
    status
  )
  values (
    v_session_id,
    v_concept_id,
    v_learning_object_id,
    v_activity_type,
    1,
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
      'reservation_version', 'review-materialization-reservation-v1',
      'source_review_state_version', v_source_review_state_version
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

create or replace function v3.mark_review_materialization_failed(
  p_materialization_id uuid,
  p_user_id uuid,
  p_session_activity_id uuid,
  p_reason text
)
returns jsonb
language plpgsql
security invoker
set search_path = v3, extensions
as $$
declare
  v_materialization v3.review_materializations;
begin
  update v3.review_materializations
  set status = case when status = 'active' then 'active' else 'failed' end,
      updated_at = now(),
      metadata = metadata || jsonb_build_object('last_failure_reason', left(coalesce(p_reason, ''), 500))
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

revoke all on function v3.review_materialization_result(v3.review_materializations, boolean) from public;
revoke all on function v3.reserve_review_materialization(jsonb) from public;
revoke all on function v3.mark_review_materialization_active(uuid, uuid, uuid) from public;
revoke all on function v3.mark_review_materialization_failed(uuid, uuid, uuid, text) from public;

grant execute on function v3.review_materialization_result(v3.review_materializations, boolean) to service_role;
grant execute on function v3.reserve_review_materialization(jsonb) to service_role;
grant execute on function v3.mark_review_materialization_active(uuid, uuid, uuid) to service_role;
grant execute on function v3.mark_review_materialization_failed(uuid, uuid, uuid, text) to service_role;

comment on table v3.review_materializations is
  'Durable idempotency reservation for one materialized review opportunity from a specific ReviewState version.';

comment on column v3.review_materializations.source_review_state_version is
  'ReviewState version used to define the materialization opportunity. It is provenance, not an attempt-time stale rejection rule.';

comment on function v3.reserve_review_materialization(jsonb) is
  'Atomically creates or reuses one review LearningSession and SessionActivity for a server-resolved ReviewState version.';
