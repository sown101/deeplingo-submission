-- B4.3: remove the Assessment chain (owner-approved plan of 2026-10-27: residual assessments are deleted, not archived).
-- Forward-only.
--
-- After B4.2 the grading lives on v3.attempts (outcome, score, graded_at, effects). Nothing writes v3.assessments or
-- v3.assessment_applications any more. This file:
--   1. counts what is about to disappear (RAISE NOTICE, to be compared with the read-only count taken before applying;
--      the owner's count is the gate, the file does not decide it);
--   2. returns mark_concept_known and quick_review_next_snapshot to the graded-attempt reads only (the legacy branch
--      was for answers stored before the backfill and is no longer needed);
--   3. drops the two old application RPCs and the columns and tables that pointed at assessments.
--
-- Order: apply 20261027110000_graded_attempt_b4_2, deploy the application, then B1 and B3, then this file (file order =
-- apply order). Precondition: no instance of the pre-B4.2 code is still serving (it would fail on the dropped tables).
-- Not applied to any environment by this file's author; applying it needs the owner's approval.

-- 1. What is about to disappear -----------------------------------------------------------------------------------

do $$
declare
  v_assessments integer;
  v_unapplied integer;
  v_known integer;
  v_events integer;
begin
  select count(*) into v_assessments from v3.assessments;
  select count(*) into v_unapplied from v3.assessments a
   where not exists (select 1 from v3.assessment_applications aa where aa.assessment_id = a.id);
  select count(*) into v_known from v3.learner_known_concepts where assessment_id is not null;
  select count(*) into v_events from v3.review_events where assessment_id is not null;
  raise notice 'b4_3 before drop: assessments=% unapplied=% known_concepts_with_assessment=% review_events_with_assessment=%',
    v_assessments, v_unapplied, v_known, v_events;
end;
$$;

-- 2. The readers read graded attempts only ------------------------------------------------------------------------

create or replace function v3.mark_concept_known(p_user_id uuid, p_session_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_session v3.learning_sessions;
  v_total integer;
  v_passed integer;
  v_attempt_id uuid;
begin
  select * into v_session from v3.learning_sessions
  where id = p_session_id and user_id = p_user_id
    and type = 'practice' and goal->>'origin' = 'known_check'
  for update;
  if v_session.id is null then
    raise exception 'known_check_conflict: session';
  end if;

  select count(*) into v_total from v3.session_activities where session_id = v_session.id;
  -- Each activity has at most one graded Attempt (the first one closes it).
  select count(*), max(t.id::text)::uuid into v_passed, v_attempt_id
  from v3.session_activities sa
  join v3.attempts t on t.activity_id = sa.id and t.user_id = p_user_id and t.graded_at is not null
  where sa.session_id = v_session.id and t.score >= 1;

  if v_total < 1 or v_passed <> v_total then
    if v_session.status in ('planned', 'active') then
      update v3.learning_sessions set status = 'completed', completed_at = now(), updated_at = now()
      where id = v_session.id;
    end if;
    return jsonb_build_object('known', false);
  end if;

  insert into v3.learner_known_concepts (
    user_id, concept_id, language_code, known_check_session_id, attempt_id
  ) values (
    p_user_id, (v_session.goal->>'concept_id')::uuid, v_session.language_code,
    v_session.id, v_attempt_id
  )
  on conflict (user_id, concept_id) do update
    set known_check_session_id = excluded.known_check_session_id,
        attempt_id = excluded.attempt_id,
        updated_at = now();

  if v_session.status in ('planned', 'active') then
    update v3.learning_sessions set status = 'completed', completed_at = now(), updated_at = now()
    where id = v_session.id;
  end if;
  return jsonb_build_object('known', true, 'attempt_id', v_attempt_id);
end;
$$;

revoke all on function v3.mark_concept_known(uuid, uuid) from public, anon, authenticated;
grant execute on function v3.mark_concept_known(uuid, uuid) to service_role;

create or replace function v3.quick_review_next_snapshot(p_user_id uuid, p_session_id uuid)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_session v3.learning_sessions;
  v_open v3.session_activities;
  v_object v3.learning_objects;
  v_segment v3.transcript_segments;
begin
  select * into v_session from v3.learning_sessions where id = p_session_id and user_id = p_user_id;
  if v_session.id is null then
    return jsonb_build_object('session', null);
  end if;

  select a.* into v_open from v3.session_activities a
  where a.session_id = v_session.id and a.status not in ('skipped', 'completed')
    and not exists (
      select 1 from v3.attempts t
      where t.activity_id = a.id and t.user_id = p_user_id and t.graded_at is not null
    )
  order by a.position
  limit 1;

  if v_open.learning_object_id is not null then
    select * into v_object from v3.learning_objects where id = v_open.learning_object_id;
    if v_object.id is not null then
      select * into v_segment from v3.transcript_segments where id = v_object.transcript_segment_id;
    end if;
  end if;

  return jsonb_build_object(
    'session', to_jsonb(v_session),
    'activities', coalesce(
      (select jsonb_agg(to_jsonb(a) order by a.position) from v3.session_activities a
       where a.session_id = v_session.id),
      '[]'::jsonb),
    'applied_activity_ids', coalesce(
      (select jsonb_agg(distinct t.activity_id) from v3.attempts t
       join v3.session_activities a on a.id = t.activity_id
       where a.session_id = v_session.id and t.user_id = p_user_id and t.graded_at is not null),
      '[]'::jsonb),
    'open_activity_id', v_open.id,
    'learning_object', case when v_object.id is null then null else to_jsonb(v_object) end,
    'concept', case when v_object.id is null then null else
      (select to_jsonb(c) from v3.concepts c where c.id = coalesce(v_open.concept_id, v_object.concept_id)) end,
    'transcript_segment', case when v_segment.id is null then null else to_jsonb(v_segment) end,
    'transcript', case when v_segment.id is null then null else
      (select to_jsonb(tr) from v3.video_transcripts tr where tr.id = v_segment.transcript_id) end
  );
end;
$$;

revoke all on function v3.quick_review_next_snapshot(uuid, uuid) from public, anon, authenticated;
grant execute on function v3.quick_review_next_snapshot(uuid, uuid) to service_role;

-- 3. Drop the old application path, then the tables -----------------------------------------------------------------

drop function if exists v3.apply_first_video_learning_assessment(jsonb);
drop function if exists v3.apply_assessment_application(jsonb);

alter table v3.learner_known_concepts drop column if exists assessment_id;
alter table v3.review_events drop column if exists assessment_id;

drop table if exists v3.assessment_applications;
drop table if exists v3.assessments;
drop type if exists v3.assessment_assessor_type;
