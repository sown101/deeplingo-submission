-- B3: remove six-dimension mastery, skill states, the old review session and its materialization reservation
-- (owner-approved plan of 2026-10-26). Forward-only.
--
-- The application no longer reads or writes v3.concept_mastery, v3.learner_skill_states or v3.review_materializations,
-- no longer starts a review session (v3.start_or_resume_review_session) or a planner-based video practice session
-- (v3.start_or_resume_video_learning_session). v3.review_states and v3.review_events (FSRS) are NOT touched; the
-- review forecast still reads them. Existing learning_sessions rows of type 'review' stay as history.
--
-- v3.apply_assessment_application is replaced first so it no longer writes mastery or skill states; its payload keys
-- 'mastery' and 'skill_states' are now ignored. Nothing calls it after B4.2 (v3.submit_graded_attempt); B4.3 drops it.
--
-- Order: apply 20261027110000_graded_attempt_b4_2 first, deploy the application, then this file (file order = apply
-- order). Not applied to any environment by this file's author; applying it needs the owner's approval. The first statement is a plain replace, the rest is drops
-- without cascade: a drop that still has a dependent object fails and rolls back the whole file.

create or replace function v3.apply_assessment_application(p_payload jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = v3, extensions
as $$
declare
  v_user_id uuid := (p_payload->>'user_id')::uuid;
  v_assessment_id uuid := (p_payload->>'assessment_id')::uuid;
  v_attempt_id uuid := (p_payload->>'attempt_id')::uuid;
  v_application_id uuid;
  v_review jsonb := p_payload->'review_transition';
  v_target jsonb;
  v_expected_version integer;
  v_row_count integer;
begin
  select id into v_application_id
  from v3.assessment_applications
  where assessment_id = v_assessment_id;

  if v_application_id is not null then
    return jsonb_build_object(
      'status', 'reused',
      'assessment_id', v_assessment_id,
      'application_id', v_application_id,
      'metadata', jsonb_build_object('application', 'already_applied')
    );
  end if;

  if not exists (
    select 1
    from v3.assessments a
    join v3.attempts t on t.id = a.attempt_id
    where a.id = v_assessment_id
      and a.attempt_id = v_attempt_id
      and t.user_id = v_user_id
  ) then
    raise exception 'assessment_application_conflict: assessment_identity';
  end if;

  if v_review is not null then
    v_target := v_review->'review_state';
    v_expected_version := (v_review->>'expected_review_state_version')::integer;
    update v3.review_states
    set stability = (v_target->>'stability')::numeric,
        difficulty = (v_target->>'difficulty')::numeric,
        elapsed_days = (v_target->>'elapsed_days')::integer,
        scheduled_days = (v_target->>'scheduled_days')::integer,
        reps = (v_target->>'reps')::integer,
        lapses = (v_target->>'lapses')::integer,
        fsrs_state = (v_target->>'fsrs_state')::v3.fsrs_state,
        due_at = (v_target->>'due_at')::timestamptz,
        last_reviewed_at = nullif(v_target->>'last_reviewed_at', '')::timestamptz,
        version = (v_target->>'version')::integer,
        updated_at = now()
    where id = (v_target->>'id')::uuid
      and user_id = v_user_id
      and concept_id = (v_target->>'concept_id')::uuid
      and review_mode = (v_target->>'review_mode')::v3.review_mode
      and version = v_expected_version;
    get diagnostics v_row_count = row_count;
    if v_row_count <> 1 then
      raise exception 'assessment_application_conflict: review_state';
    end if;

    insert into v3.review_events (
      review_state_id, assessment_id, attempt_id, review_mode, rating,
      provenance, previous_scheduling_state, resulting_scheduling_state, reviewed_at
    )
    values (
      ((v_review->'review_event')->>'review_state_id')::uuid,
      v_assessment_id,
      v_attempt_id,
      ((v_review->'review_event')->>'review_mode')::v3.review_mode,
      ((v_review->'review_event')->>'rating')::integer,
      (v_review->'review_event')->>'provenance',
      (v_review->'review_event')->'previous_scheduling_state',
      (v_review->'review_event')->'resulting_scheduling_state',
      ((v_review->'review_event')->>'reviewed_at')::timestamptz
    );
  end if;

  insert into v3.assessment_applications (assessment_id, attempt_id, user_id, status, metadata)
  values (v_assessment_id, v_attempt_id, v_user_id, 'applied', coalesce(p_payload->'metadata', '{}'::jsonb))
  returning id into v_application_id;

  return jsonb_build_object(
    'status', 'applied',
    'assessment_id', v_assessment_id,
    'application_id', v_application_id,
    'metadata', jsonb_build_object('application', 'applied')
  );
exception
  when unique_violation then
    select id into v_application_id
    from v3.assessment_applications
    where assessment_id = v_assessment_id;
    if v_application_id is not null then
      return jsonb_build_object(
        'status', 'reused',
        'assessment_id', v_assessment_id,
        'application_id', v_application_id,
        'metadata', jsonb_build_object('application', 'already_applied')
      );
    end if;
    raise;
end;
$$;

revoke all on function v3.apply_assessment_application(jsonb) from public, anon, authenticated;
grant execute on function v3.apply_assessment_application(jsonb) to service_role;

comment on function v3.apply_assessment_application(jsonb) is
  'Atomic persistence boundary for server-computed assessment effects (review state and event). FSRS and learning policy are computed in Python.';

drop function if exists v3.start_or_resume_review_session(uuid, text, jsonb, integer);
drop function if exists v3.start_or_resume_video_learning_session(uuid, uuid, uuid, text, text, text, jsonb);
drop function if exists v3.reserve_review_materialization(jsonb);
drop function if exists v3.mark_review_materialization_active(uuid, uuid, uuid);
drop function if exists v3.mark_review_materialization_failed(uuid, uuid, uuid, text);
drop function if exists v3.review_materialization_result(v3.review_materializations, boolean);

drop table if exists v3.review_materializations;
drop table if exists v3.learner_skill_states;
drop table if exists v3.concept_mastery;

drop type if exists v3.mastery_state;
drop type if exists v3.skill_type;
