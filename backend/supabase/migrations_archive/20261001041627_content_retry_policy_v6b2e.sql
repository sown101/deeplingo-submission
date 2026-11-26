-- 6B-2E: LOCAL/PREPARED ONLY. Separate owner authorization required for hosted apply.
-- Quiesce API admission + old workers/Beat; inspect queues, never purge.
begin;
do $$ begin
  if exists (select 1 from v3.video_work_intents where state = 'running') then
    raise exception '6B-2E requires a drained running-intent cutover' using errcode = '23514';
  end if;
end $$;

alter table v3.video_work_intents
  add column failure_class text,
  add column failure_code text,
  add column last_error_at timestamptz,
  add column next_retry_at timestamptz,
  add constraint video_work_failure_metadata_chk check (
    (failure_class is null and failure_code is null and last_error_at is null)
    or (failure_class is not null and failure_class in ('transient', 'permanent', 'unknown')
      and failure_code is not null and failure_code in (
        'transient_timeout', 'transient_network', 'provider_rate_limit', 'provider_temporary',
        'database_temporary', 'content_unavailable', 'validation_failed', 'invariant_violation',
        'configuration_error', 'unknown_failure', 'lease_lost', 'retry_exhausted')
      and last_error_at is not null));
-- No history rewrite; claim_epoch already counts all execution claims.

create or replace function v3.claim_leased_content_work(
  p_intent_id uuid, p_preparation_version text default null, p_lease_seconds integer default 2100
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; v v3.videos%rowtype; ts timestamptz;
begin
  if p_lease_seconds is null or p_lease_seconds < 1 or p_lease_seconds > 86400 then
    raise exception 'Invalid Content lease' using errcode = '22023';
  end if;
  select * into i from v3.video_work_intents where id = p_intent_id;
  if not found then return null; end if;
  select * into v from v3.videos where id = i.video_id for update;
  if not found then return null; end if;
  select * into i from v3.video_work_intents where id = p_intent_id for update;
  ts := clock_timestamp();
  if i.state not in ('pending', 'dispatched')
     or (i.state = 'pending' and i.next_dispatch_at > ts)
     or (i.next_retry_at is not null and i.next_retry_at > ts) then return null; end if;
  if i.claim_epoch >= case when i.stage = 'transcript' then 4 else 3 end then
  if i.stage = 'transcript' then
    update v3.videos set processing_status = 'failed', processing_error = null,
      processing_error_code = 'processing_failed', processing_retryable = true,
      processing_completed_at = ts, updated_at = ts where id = i.video_id;
  else
    update v3.videos set learning_status = 'failed', learning_failure_code = 'preparation_failed',
      learning_retryable = true, learning_completed_at = ts, updated_at = ts where id = i.video_id;
  end if;
    update v3.video_work_intents set state = 'failed', completed_at = ts,
      claim_token = null, lease_expires_at = null, next_retry_at = null, updated_at = ts,
      failure_code = coalesce(failure_code, 'retry_exhausted'),
      failure_class = coalesce(failure_class, 'transient'), last_error_at = ts where id = i.id;
    return null;
  end if;
  if i.stage = 'transcript' then
    if v.processing_status not in ('pending', 'processing') then return null; end if;
    update v3.videos set processing_status = 'processing', processing_error = null,
      processing_error_code = null, processing_retryable = false,
      processing_started_at = ts, processing_completed_at = null, updated_at = ts where id = v.id;
  else
    if p_preparation_version is null or btrim(p_preparation_version) = ''
       or v.learning_status not in ('not_started', 'processing')
       or v.processing_status not in ('transcript_ready', 'learning_objects_ready') then return null; end if;
    update v3.videos set learning_status = 'processing', learning_preparation_version = p_preparation_version,
      learning_failure_code = null, learning_retryable = false,
      learning_started_at = ts, learning_completed_at = null, updated_at = ts where id = v.id;
  end if;
  update v3.video_work_intents set state = 'running', claim_token = extensions.gen_random_uuid(),
    claim_epoch = claim_epoch + 1, claimed_at = ts, next_retry_at = null,
    lease_expires_at = ts + make_interval(secs => p_lease_seconds), updated_at = ts
    where id = i.id returning * into i;
  return to_jsonb(i);
end $$;

create or replace function v3.recover_expired_content_work(p_limit integer default 50)
returns integer language plpgsql security invoker set search_path = '' as $$
declare candidate record; i v3.video_work_intents%rowtype; recovered integer := 0; ts timestamptz;
begin
  if p_limit is null or p_limit < 1 or p_limit > 100 then
    raise exception 'Recovery limit must be 1..100' using errcode = '22023';
  end if;
  for candidate in select id, video_id from v3.video_work_intents
    where state = 'running' and lease_expires_at <= clock_timestamp()
    order by lease_expires_at, id limit p_limit
  loop
    perform 1 from v3.videos where id = candidate.video_id for update skip locked;
    if not found then continue; end if;
    select * into i from v3.video_work_intents where id = candidate.id for update;
    ts := clock_timestamp();
    if i.state <> 'running' or i.lease_expires_at > ts then continue; end if;
    if i.claim_epoch >= case when i.stage = 'transcript' then 4 else 3 end then
  if i.stage = 'transcript' then
    update v3.videos set processing_status = 'failed', processing_error = null,
      processing_error_code = 'processing_failed', processing_retryable = true,
      processing_completed_at = ts, updated_at = ts where id = i.video_id;
  else
    update v3.videos set learning_status = 'failed', learning_failure_code = 'preparation_failed',
      learning_retryable = true, learning_completed_at = ts, updated_at = ts where id = i.video_id;
  end if;
      update v3.video_work_intents set state = 'failed', claim_token = null,
        lease_expires_at = null, recovery_count = recovery_count + 1, completed_at = ts, next_retry_at = null,
        failure_class = 'transient', failure_code = 'lease_lost', last_error_at = ts,
        updated_at = ts where id = i.id;
    else
      update v3.video_work_intents set state = 'pending', claim_token = null,
        lease_expires_at = null, recovery_count = recovery_count + 1,
        failure_class = 'transient', failure_code = 'lease_lost', last_error_at = ts,
        next_dispatch_at = ts + make_interval(secs => (60 * power(2, i.claim_epoch - 1))::integer),
        next_retry_at = ts + make_interval(secs => (60 * power(2, i.claim_epoch - 1))::integer),
        updated_at = ts where id = i.id;
    end if;
    recovered := recovered + 1;
  end loop;
  return recovered;
end $$;

create or replace function v3.admit_video_content_work(
  p_user_id uuid, p_video_id uuid, p_action text, p_library_item_id uuid default null
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_video v3.videos%rowtype;
  v_membership v3.learner_videos%rowtype;
  v_intent v3.video_work_intents%rowtype;
  v_stage text;
  v_command text := 'reused';
  v_generation integer;
  v_dispatch_now boolean := false;
begin
  if p_user_id is null or p_video_id is null or p_action is null
     or p_action not in ('import', 'retry_transcript', 'retry_preparation') then
    raise exception 'Invalid Content work admission' using errcode = '22023';
  end if;
  -- Serialize only new-work admission, before any Video lock. Handoff replaces
  -- its running transcript with preparation atomically: net active count <= 0.
  perform pg_advisory_xact_lock(6202050::bigint);
  select * into v_video from v3.videos where id = p_video_id for update;
  if not found then
    raise exception 'Video not found' using errcode = 'P0002';
  end if;

  if p_action = 'import' then
    insert into v3.learner_videos (user_id, video_id)
      values (p_user_id, p_video_id)
      on conflict (user_id, video_id) do update set updated_at = now()
      returning * into v_membership;
  else
    select * into v_membership from v3.learner_videos
      where id = p_library_item_id and user_id = p_user_id and video_id = p_video_id;
    if not found then
      raise exception 'Library item not found' using errcode = 'P0002';
    end if;
  end if;

  if p_action = 'retry_transcript' then
    if v_video.processing_status <> 'failed' or not v_video.processing_retryable then
      raise exception 'Video is not retryable' using errcode = '23514';
    end if;
    update v3.video_work_intents set state = 'failed', completed_at = now(), updated_at = now()
      where video_id = p_video_id and stage = 'transcript'
        and state in ('pending', 'dispatched', 'running');
    update v3.videos set processing_status = 'pending', processing_error = null,
      processing_error_code = null, processing_retryable = false,
      processing_started_at = null, processing_completed_at = null, updated_at = now()
      where id = p_video_id returning * into v_video;
    v_stage := 'transcript';
    v_command := 'retry_accepted';
  elsif p_action = 'retry_preparation' then
    if v_video.processing_status not in ('transcript_ready', 'learning_objects_ready')
       or v_video.learning_status <> 'failed' or not v_video.learning_retryable then
      raise exception 'Learning preparation is not retryable' using errcode = '23514';
    end if;
    update v3.video_work_intents set state = 'failed', completed_at = now(), updated_at = now()
      where video_id = p_video_id and stage = 'learning_preparation'
        and state in ('pending', 'dispatched', 'running');
    update v3.videos set learning_status = 'not_started', learning_failure_code = null,
      learning_retryable = false, learning_started_at = null,
      learning_completed_at = null, updated_at = now()
      where id = p_video_id returning * into v_video;
    v_stage := 'learning_preparation';
    v_command := 'learning_retry_accepted';
  elsif v_video.processing_status = 'pending' then
    v_stage := 'transcript';
  elsif v_video.processing_status = 'failed' and v_video.processing_retryable then
    update v3.video_work_intents set state = 'failed', completed_at = now(), updated_at = now()
      where video_id = p_video_id and stage = 'transcript'
        and state in ('pending', 'dispatched', 'running');
    update v3.videos set processing_status = 'pending', processing_error = null,
      processing_error_code = null, processing_retryable = false,
      processing_started_at = null, processing_completed_at = null, updated_at = now()
      where id = p_video_id returning * into v_video;
    v_stage := 'transcript';
    v_command := 'retry_accepted';
  elsif v_video.processing_status in ('transcript_ready', 'learning_objects_ready')
        and v_video.learning_status = 'not_started' then
    v_stage := 'learning_preparation';
  end if;

  if v_stage is not null then
    select * into v_intent from v3.video_work_intents
      where video_id = p_video_id and stage = v_stage
        and state in ('pending', 'dispatched', 'running')
      order by generation desc limit 1;
    if not found then
      select coalesce(max(generation), 0) + 1 into v_generation
        from v3.video_work_intents where video_id = p_video_id and stage = v_stage;
      -- Safety cap: one existing reconciler batch, not a measured capacity claim.
      if (select count(*) from v3.video_work_intents
          where state in ('pending', 'dispatched', 'running')) >= 50 then
        raise exception 'Content admission temporarily unavailable' using errcode = 'DL002';
      end if;
      insert into v3.video_work_intents (video_id, stage, generation)
        values (p_video_id, v_stage, v_generation) returning * into v_intent;
      v_dispatch_now := true;
      if v_command = 'reused' and v_stage = 'transcript' then
        v_command := 'accepted';
      end if;
    end if;
  end if;

  return jsonb_build_object(
    'association', to_jsonb(v_membership), 'video', to_jsonb(v_video),
    'intent_id', v_intent.id, 'command_status', v_command,
    'dispatch_now', v_dispatch_now
  );
end;
$$;

create function v3.record_content_work_failure(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint,
  p_failure_class text, p_failure_code text, p_explicit_retry boolean
) returns text language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; stage_name text; ts timestamptz; delay_seconds integer;
begin
  select stage into stage_name from v3.video_work_intents where id = p_intent_id;
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, stage_name);
  if p_failure_class is null or p_failure_class not in ('transient', 'permanent', 'unknown')
     or p_failure_code is null or p_failure_code not in (
       'transient_timeout', 'transient_network', 'provider_rate_limit', 'provider_temporary',
       'database_temporary', 'content_unavailable', 'validation_failed', 'invariant_violation',
       'configuration_error', 'unknown_failure')
     or p_explicit_retry is null or (p_failure_class = 'permanent' and p_explicit_retry) then
    raise exception 'Invalid safe Content failure' using errcode = '22023';
  end if;
  ts := clock_timestamp();
  if p_failure_class = 'transient'
     and i.claim_epoch < case when i.stage = 'transcript' then 4 else 3 end then
    delay_seconds := (60 * power(2, i.claim_epoch - 1))::integer;
  end if;
  if i.stage = 'transcript' then
    update v3.videos set processing_status = case when delay_seconds is null then 'failed'::v3.processing_status else 'pending'::v3.processing_status end,
      processing_error = null, processing_error_code = case when delay_seconds is null then 'processing_failed' else null end,
      processing_retryable = delay_seconds is null and p_explicit_retry,
      processing_completed_at = case when delay_seconds is null then ts else null end, updated_at = ts where id = i.video_id;
  else
    update v3.videos set learning_status = case when delay_seconds is null then 'failed' else 'not_started' end,
      learning_failure_code = case when delay_seconds is null then 'preparation_failed' else null end,
      learning_retryable = delay_seconds is null and p_explicit_retry,
      learning_completed_at = case when delay_seconds is null then ts else null end, updated_at = ts where id = i.video_id;
  end if;
  update v3.video_work_intents set state = case when delay_seconds is null then 'failed' else 'pending' end,
    claim_token = null, lease_expires_at = null,
    completed_at = case when delay_seconds is null then ts else null end,
    failure_class = p_failure_class, failure_code = p_failure_code, last_error_at = ts,
    next_dispatch_at = ts + make_interval(secs => coalesce(delay_seconds, 0)),
    next_retry_at = case when delay_seconds is null then null else ts + make_interval(secs => delay_seconds) end,
    updated_at = ts where id = i.id;
  return case when delay_seconds is null then 'failed' else 'pending' end;
end $$;

-- Old Celery-countdown writer could multiply budgets after redispatch. Fail closed.
create or replace function v3.fail_claimed_content_work(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_failure_code text,
  p_retryable boolean, p_retry_delay integer default null
) returns text language plpgsql security invoker set search_path = '' as $$
begin raise exception 'Bounded Content failure contract required' using errcode = 'DL001'; end $$;
revoke all on function v3.fail_claimed_content_work(uuid, uuid, bigint, text, boolean, integer) from public, anon, authenticated, service_role;

revoke all on function v3.claim_leased_content_work(uuid, text, integer) from public, anon, authenticated;
grant execute on function v3.claim_leased_content_work(uuid, text, integer) to service_role;
revoke all on function v3.recover_expired_content_work(integer) from public, anon, authenticated;
grant execute on function v3.recover_expired_content_work(integer) to service_role;
revoke all on function v3.admit_video_content_work(uuid, uuid, text, uuid) from public, anon, authenticated;
grant execute on function v3.admit_video_content_work(uuid, uuid, text, uuid) to service_role;
revoke all on function v3.record_content_work_failure(uuid, uuid, bigint, text, text, boolean) from public, anon, authenticated;
grant execute on function v3.record_content_work_failure(uuid, uuid, bigint, text, text, boolean) to service_role;
commit;
