-- 6B-2B: Content V3 durable admission and post-commit delivery intent.
-- Cutover is forward-only: no historical video/status backfill.

create table v3.video_work_intents (
  id uuid primary key default extensions.gen_random_uuid(),
  video_id uuid not null references v3.videos(id) on delete cascade,
  stage text not null check (stage in ('transcript', 'learning_preparation')),
  generation integer not null check (generation > 0),
  state text not null default 'pending' check (state in ('pending', 'dispatched', 'running', 'completed', 'failed')),
  next_dispatch_at timestamptz not null default now(),
  last_dispatched_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint video_work_intents_generation_unique unique (video_id, stage, generation)
);

create unique index video_work_intents_one_active_stage_idx
  on v3.video_work_intents (video_id, stage)
  where state in ('pending', 'dispatched', 'running');
create index video_work_intents_due_idx
  on v3.video_work_intents (next_dispatch_at, created_at)
  where state in ('pending', 'dispatched');

alter table v3.video_work_intents enable row level security;
revoke all on table v3.video_work_intents from public, anon, authenticated;
grant select, insert, update, delete on table v3.video_work_intents to service_role;
comment on table v3.video_work_intents is
  'Server-owned Content V3 work delivery identity; Video status remains product readiness.';

-- The API already verifies CurrentUser. The invoker RPC additionally checks
-- membership on retries, locks the global Video and admits one stage generation.
-- YouTube metadata/Video creation may precede this call, but no learner work is
-- accepted until membership and intent commit together in this transaction.
create function v3.admit_video_content_work(
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
revoke all on function v3.admit_video_content_work(uuid, uuid, text, uuid) from public, anon, authenticated;
grant execute on function v3.admit_video_content_work(uuid, uuid, text, uuid) to service_role;

-- Claim is atomic with the product processing transition. No lease/fencing of
-- already-running workers is introduced here; that remains B2-02 / 6B-2C.
create function v3.claim_video_content_work(p_intent_id uuid, p_preparation_version text default null)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_intent v3.video_work_intents%rowtype;
  v_video v3.videos%rowtype;
begin
  select * into v_intent from v3.video_work_intents where id = p_intent_id;
  if not found then return null; end if;
  select * into v_video from v3.videos where id = v_intent.video_id for update;
  if not found then return null; end if;
  select * into v_intent from v3.video_work_intents where id = p_intent_id for update;
  if v_intent.state not in ('pending', 'dispatched') then return null; end if;

  if v_intent.stage = 'transcript' then
    if v_video.processing_status <> 'pending' then return null; end if;
    update v3.videos set processing_status = 'processing', processing_error = null,
      processing_error_code = null, processing_retryable = false,
      processing_started_at = now(), processing_completed_at = null, updated_at = now()
      where id = v_video.id;
  elsif v_intent.stage = 'learning_preparation' then
    if p_preparation_version is null or btrim(p_preparation_version) = ''
       or v_video.learning_status <> 'not_started'
       or v_video.processing_status not in ('transcript_ready', 'learning_objects_ready') then
      return null;
    end if;
    update v3.videos set learning_status = 'processing',
      learning_preparation_version = p_preparation_version,
      learning_failure_code = null, learning_retryable = false,
      learning_started_at = now(), learning_completed_at = null, updated_at = now()
      where id = v_video.id;
  else
    return null;
  end if;
  update v3.video_work_intents set state = 'running', updated_at = now()
    where id = p_intent_id returning * into v_intent;
  return to_jsonb(v_intent);
end;
$$;
revoke all on function v3.claim_video_content_work(uuid, text) from public, anon, authenticated;
grant execute on function v3.claim_video_content_work(uuid, text) to service_role;

-- This short transaction removes the second DB -> broker gap. Partial
-- transcript/segment writes occurred earlier; no external call is inside it.
create function v3.complete_transcript_content_work(p_intent_id uuid)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_intent v3.video_work_intents%rowtype;
  v_video v3.videos%rowtype;
  v_preparation_id uuid;
  v_generation integer;
begin
  select * into v_intent from v3.video_work_intents where id = p_intent_id;
  if not found or v_intent.stage <> 'transcript' then
    raise exception 'Transcript work intent not found' using errcode = 'P0002';
  end if;
  select * into v_video from v3.videos where id = v_intent.video_id for update;
  select * into v_intent from v3.video_work_intents where id = p_intent_id for update;
  if v_intent.state = 'completed' and v_video.processing_status = 'transcript_ready' then
    select id into v_preparation_id from v3.video_work_intents
      where video_id = v_video.id and stage = 'learning_preparation'
      order by generation desc limit 1;
    return jsonb_build_object('video', to_jsonb(v_video), 'preparation_intent_id', v_preparation_id);
  end if;
  if v_intent.state <> 'running' or v_video.processing_status <> 'processing' then
    raise exception 'Transcript work is no longer current' using errcode = '23514';
  end if;

  update v3.videos set processing_status = 'transcript_ready',
    processing_error = null, processing_error_code = null,
    processing_retryable = false, processing_completed_at = now(), updated_at = now()
    where id = v_video.id returning * into v_video;
  update v3.video_work_intents set state = 'completed', completed_at = now(), updated_at = now()
    where id = p_intent_id;
  if v_video.learning_status = 'not_started' then
    select id into v_preparation_id from v3.video_work_intents
      where video_id = v_video.id and stage = 'learning_preparation'
        and state in ('pending', 'dispatched', 'running')
      order by generation desc limit 1;
    if v_preparation_id is null then
      select coalesce(max(generation), 0) + 1 into v_generation
        from v3.video_work_intents where video_id = v_video.id and stage = 'learning_preparation';
      insert into v3.video_work_intents (video_id, stage, generation)
        values (v_video.id, 'learning_preparation', v_generation)
        returning id into v_preparation_id;
    end if;
  end if;
  return jsonb_build_object('video', to_jsonb(v_video), 'preparation_intent_id', v_preparation_id);
end;
$$;
revoke all on function v3.complete_transcript_content_work(uuid) from public, anon, authenticated;
grant execute on function v3.complete_transcript_content_work(uuid) to service_role;

-- A retry remains the same logical generation. The business reset and
-- re-dispatch eligibility commit together; self.retry publish can fail safely.
create function v3.reset_failed_video_content_work(p_intent_id uuid, p_delay_seconds integer)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare
  v_intent v3.video_work_intents%rowtype;
  v_video v3.videos%rowtype;
begin
  if p_delay_seconds < 0 or p_delay_seconds > 3600 then
    raise exception 'Invalid retry delay' using errcode = '22023';
  end if;
  select * into v_intent from v3.video_work_intents where id = p_intent_id;
  if not found then return false; end if;
  select * into v_video from v3.videos where id = v_intent.video_id for update;
  select * into v_intent from v3.video_work_intents where id = p_intent_id for update;
  if v_intent.state <> 'running' then return false; end if;
  if v_intent.stage = 'transcript' and v_video.processing_status = 'failed' and v_video.processing_retryable then
    update v3.videos set processing_status = 'pending', processing_error = null,
      processing_error_code = null, processing_retryable = false,
      processing_started_at = null, processing_completed_at = null, updated_at = now()
      where id = v_video.id;
  elsif v_intent.stage = 'learning_preparation' and v_video.learning_status = 'failed' and v_video.learning_retryable then
    update v3.videos set learning_status = 'not_started', learning_failure_code = null,
      learning_retryable = false, learning_started_at = null,
      learning_completed_at = null, updated_at = now()
      where id = v_video.id;
  else
    return false;
  end if;
  update v3.video_work_intents set state = 'pending',
    next_dispatch_at = now() + make_interval(secs => p_delay_seconds), updated_at = now()
    where id = p_intent_id;
  return true;
end;
$$;
revoke all on function v3.reset_failed_video_content_work(uuid, integer) from public, anon, authenticated;
grant execute on function v3.reset_failed_video_content_work(uuid, integer) to service_role;
