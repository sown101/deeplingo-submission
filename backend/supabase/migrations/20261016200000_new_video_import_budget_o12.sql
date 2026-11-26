-- O12: a per-learner budget for importing videos that still need AI work.
--
-- Importing a video nobody has prepared yet costs AI transcription and preparation. This ledger
-- records which learner paid for which video; `v3.charge_new_video_import` counts the learner's
-- charges in a rolling window under a per-learner advisory lock, so two concurrent imports cannot
-- both take the last slot. A learner is charged once per video: importing it again, or retrying
-- it after a failure, is free. Videos that are already prepared are never charged (the caller
-- skips the call). Service role only; clients have no grant. Forward-only.

create table if not exists v3.learner_new_video_imports (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  video_id uuid not null references v3.videos(id) on delete cascade,
  imported_at timestamptz not null default now(),
  primary key (user_id, video_id)
);

comment on table v3.learner_new_video_imports is
  'O12: one row per learner and video that needed AI work when imported; counted against the '
  'learner''s rolling new-video budget by v3.charge_new_video_import.';

create index if not exists learner_new_video_imports_user_time_idx
  on v3.learner_new_video_imports (user_id, imported_at desc);

alter table v3.learner_new_video_imports enable row level security;
revoke all privileges on v3.learner_new_video_imports from anon, authenticated;
grant all privileges on v3.learner_new_video_imports to service_role;

create or replace function v3.charge_new_video_import(
  p_user_id uuid,
  p_video_id uuid,
  p_limit integer,
  p_window_seconds integer
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_used integer;
  v_oldest timestamptz;
begin
  if p_limit is null or p_limit < 1 or p_limit > 1000
      or p_window_seconds is null or p_window_seconds < 60 or p_window_seconds > 2678400 then
    raise exception 'new_video_budget_conflict: invalid_policy';
  end if;

  -- One learner is charged one import at a time.
  perform pg_advisory_xact_lock(hashtextextended('new_video_import:' || p_user_id::text, 0));

  select count(*), min(imported_at) into v_used, v_oldest
  from v3.learner_new_video_imports
  where user_id = p_user_id
    and imported_at > now() - make_interval(secs => p_window_seconds);

  if exists (
    select 1 from v3.learner_new_video_imports where user_id = p_user_id and video_id = p_video_id
  ) then
    return jsonb_build_object('allowed', true, 'charged', false, 'used', v_used, 'limit', p_limit,
                              'reset_at', null);
  end if;

  if v_used >= p_limit then
    return jsonb_build_object('allowed', false, 'charged', false, 'used', v_used, 'limit', p_limit,
                              'reset_at', v_oldest + make_interval(secs => p_window_seconds));
  end if;

  insert into v3.learner_new_video_imports (user_id, video_id) values (p_user_id, p_video_id);
  return jsonb_build_object('allowed', true, 'charged', true, 'used', v_used + 1, 'limit', p_limit,
                            'reset_at', null);
end;
$$;

revoke all on function v3.charge_new_video_import(uuid, uuid, integer, integer)
  from public, anon, authenticated;
grant execute on function v3.charge_new_video_import(uuid, uuid, integer, integer) to service_role;
