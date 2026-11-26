-- A25. Forward-only; replaces only the body of v3.create_or_reconcile_attempt (6B-1C).
-- The RPC already locks the owned activity row; it now refuses a NEW Attempt when that row is
-- no longer `active` (for example a Quick review question closed as `skipped` by
-- v3.skip_quick_review_item after the Python execution check passed). The status is read under
-- the same row lock the skip takes, so an answer and a skip of one question are serialized:
-- either the Attempt is stored on the active question, or the closed question gets no Attempt.
-- An existing submission_id still reconciles to its stored Attempt whatever the status is now,
-- so a lost receipt for an answer stored before the close is never turned into an error.
-- Ownership is still checked before the status and before any key lookup (no existence oracle).
create or replace function v3.create_or_reconcile_attempt(
  p_user_id uuid, p_activity_id uuid, p_submission_id uuid,
  p_response_payload jsonb, p_started_at timestamptz default null,
  p_submitted_at timestamptz default null, p_duration_ms integer default null,
  p_client_metadata jsonb default '{}'::jsonb
) returns jsonb language plpgsql security invoker
set search_path = '' set lock_timeout = '3s' set statement_timeout = '10s' as $$
declare
  v_attempt v3.attempts%rowtype;
  v_status v3.activity_status;
  v_number integer;
  v_created boolean;
begin
  if p_submission_id is null or p_response_payload is null
     or jsonb_typeof(p_response_payload) <> 'object' then
    raise exception using errcode = '22023', message = 'invalid_submission';
  end if;
  -- Short per-execution serialization allocates history numbers without races.
  -- Ownership is checked BEFORE any key lookup; no foreign existence oracle.
  select a.status into v_status from v3.session_activities a
    join v3.learning_sessions s on s.id = a.session_id
    where a.id = p_activity_id and s.user_id = p_user_id
    for update of a;
  if not found then
    raise exception using errcode = 'P0002', message = 'activity_not_found';
  end if;
  select * into v_attempt from v3.attempts
    where user_id = p_user_id and submission_id = p_submission_id;
  if not found then
    -- Only an active question takes a new answer (A25).
    if v_status is distinct from 'active'::v3.activity_status then
      raise exception using errcode = '55000', message = 'activity_closed';
    end if;
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
