-- 6B-1C. Forward-only; historical IDs/numbers/relationships are untouched.
-- Legacy NULL keys are readable, but every future insert requires a UUID key.
alter table v3.attempts add column submission_id uuid;
alter table v3.attempts add constraint attempts_unique_submission
  unique (user_id, submission_id);
comment on column v3.attempts.submission_id is
  'Opaque transport identity scoped to verified learner; never pedagogical authority.';

create function v3.protect_immutable_attempt() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if TG_OP = 'INSERT' and NEW.submission_id is null then
    raise exception using errcode = '23502', message = 'submission_id_required';
  end if;
  if TG_OP = 'UPDATE' and NEW is distinct from OLD then
    raise exception using errcode = '23514', message = 'attempt_immutable';
  end if;
  return NEW;
end;
$$;
create trigger attempts_immutable
before insert or update on v3.attempts
for each row execute function v3.protect_immutable_attempt();
revoke all on function v3.protect_immutable_attempt() from public, anon, authenticated;

create function v3.create_or_reconcile_attempt(
  p_user_id uuid, p_activity_id uuid, p_submission_id uuid,
  p_response_payload jsonb, p_started_at timestamptz default null,
  p_submitted_at timestamptz default null, p_duration_ms integer default null,
  p_client_metadata jsonb default '{}'::jsonb
) returns jsonb language plpgsql security invoker
set search_path = '' set lock_timeout = '3s' set statement_timeout = '10s' as $$
declare
  v_attempt v3.attempts%rowtype;
  v_number integer;
  v_created boolean;
begin
  if p_submission_id is null or p_response_payload is null
     or jsonb_typeof(p_response_payload) <> 'object' then
    raise exception using errcode = '22023', message = 'invalid_submission';
  end if;
  -- Short per-execution serialization allocates history numbers without races.
  -- Ownership is checked BEFORE any key lookup; no foreign existence oracle.
  perform a.id from v3.session_activities a
    join v3.learning_sessions s on s.id = a.session_id
    where a.id = p_activity_id and s.user_id = p_user_id
    for update of a;
  if not found then
    raise exception using errcode = 'P0002', message = 'activity_not_found';
  end if;
  select * into v_attempt from v3.attempts
    where user_id = p_user_id and submission_id = p_submission_id;
  if not found then
    select coalesce(max(attempt_number), 0) + 1 into v_number from v3.attempts
      where activity_id = p_activity_id and user_id = p_user_id;
    insert into v3.attempts (
      activity_id, user_id, submission_id, attempt_number, status,
      response_payload, started_at, submitted_at, duration_ms, client_metadata
    ) values (
      p_activity_id, p_user_id, p_submission_id, v_number, 'submitted',
      p_response_payload, p_started_at, coalesce(p_submitted_at, now()),
      p_duration_ms, p_client_metadata
    ) on conflict (user_id, submission_id) do nothing returning * into v_attempt;
    v_created := found;
    if not v_created then
      -- A concurrent request for another owned activity may have won this key.
      select * into strict v_attempt from v3.attempts
        where user_id = p_user_id and submission_id = p_submission_id;
    end if;
  else
    v_created := false;
  end if;
  -- JSONB structural comparison: object order irrelevant, text/arrays unchanged.
  -- Observation metadata/timing is first-write-wins, NEVER updated on reuse.
  if v_attempt.activity_id <> p_activity_id
     or v_attempt.response_payload is distinct from p_response_payload then
    raise exception using errcode = '23505', message = 'submission_conflict';
  end if;
  return jsonb_build_object('attempt', to_jsonb(v_attempt), 'created', v_created);
end;
$$;
revoke all on function v3.create_or_reconcile_attempt(uuid, uuid, uuid, jsonb, timestamptz, timestamptz, integer, jsonb)
  from public, anon, authenticated;
grant execute on function v3.create_or_reconcile_attempt(uuid, uuid, uuid, jsonb, timestamptz, timestamptz, integer, jsonb)
  to service_role;
