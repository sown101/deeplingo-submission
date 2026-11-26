-- B4.2: one graded answer in one step (owner-approved plan of 2026-10-26, option B). Additive and forward-only.
--
-- An Attempt now carries its own grading (outcome, score, graded_at, effects, grader), written once, when the
-- Attempt is inserted, by v3.submit_graded_attempt together with the ReviewState / ReviewEvent change and the
-- optional usage-ladder event, in one transaction. The first graded answer closes the activity (D4): a second
-- graded Attempt for the same activity is refused (unique index and an explicit check); the same submission_id
-- returns the stored result. v3.assessments and v3.assessment_applications are no longer written by the
-- application; they are dropped in B4.3.
--
-- Grading detail (the old `feedback`) is deliberately not stored on attempts: learners can read their own attempts
-- through the Data API (SEC-01 revoked it for assessments), and only the outcome is needed.
--
-- v3.mark_concept_known and v3.quick_review_next_snapshot read the graded Attempts, and still accept an Attempt that
-- only has an applied Assessment (an answer the previous application version stored after the backfill ran), so the
-- time between applying this file and deploying the application loses no answer. B4.3 removes that legacy branch.
-- v3.review_events no longer needs an Assessment: the Attempt is its idempotency identity.
--
-- Deploy order: apply this file first, then the application version of this change, then the drops
-- (20261027120000_drop_ai_cost_ledger_b1, 20261027130000_drop_mastery_review_session_b3) and B4.3.
-- Not applied to any environment by this file's author; applying it needs the owner's approval.

-- 1. Grading columns on attempts --------------------------------------------------------------------------

alter table v3.attempts add column if not exists outcome text;
alter table v3.attempts add column if not exists score numeric;
alter table v3.attempts add column if not exists graded_at timestamptz;
alter table v3.attempts add column if not exists effects text;
alter table v3.attempts add column if not exists grader text;

-- Backfill: every binary Assessment already stored, applied or not, so an answer whose application never
-- completed is not lost. One attempt per activity (the unique index below needs it): the applied one if any (the
-- one the previous mark_concept_known counted), otherwise the earliest. Assessments left out here (a non-binary
-- score, or a later attempt of an activity that already has its graded one) stay in v3.assessments until B4.3
-- decides their archive. The immutability trigger forbids any update, so it is off for this statement only.
alter table v3.attempts disable trigger attempts_immutable;

with chosen as (
  select distinct on (t.activity_id, t.user_id)
         t.id as attempt_id, a.overall_score, a.assessed_at, a.created_at, a.assessor_type
    from v3.attempts as t
    join v3.assessments as a on a.attempt_id = t.id
    left join v3.assessment_applications as aa on aa.assessment_id = a.id
   where a.overall_score in (0, 1)
   order by t.activity_id, t.user_id,
            (aa.id is not null) desc, aa.applied_at desc nulls last, t.attempt_number
)
update v3.attempts as t
   set outcome = case when c.overall_score >= 1 then 'correct' else 'incorrect' end,
       score = c.overall_score,
       graded_at = coalesce(c.assessed_at, c.created_at),
       effects = case when exists (select 1 from v3.review_events e where e.attempt_id = t.id)
                      then 'review_state' else 'practice_only' end,
       grader = c.assessor_type
  from chosen as c
 where t.id = c.attempt_id;

alter table v3.attempts enable trigger attempts_immutable;

alter table v3.attempts drop constraint if exists attempts_graded_consistent_chk;
alter table v3.attempts add constraint attempts_graded_consistent_chk check (
  (graded_at is null and outcome is null and score is null and effects is null)
  or (graded_at is not null and outcome in ('correct', 'incorrect') and score in (0, 1)
      and effects in ('none', 'practice_only', 'review_state')
      and (outcome = 'correct') = (score = 1))
);

create unique index if not exists attempts_one_graded_per_activity_idx
  on v3.attempts (activity_id, user_id) where graded_at is not null;

comment on column v3.attempts.outcome is 'correct or incorrect; set with the grade, never updated (B4.2).';
comment on column v3.attempts.score is 'Binary score (0 or 1) of the graded answer; set with the grade.';
comment on column v3.attempts.graded_at is 'Null for an ungraded legacy Attempt; the first graded Attempt closes its activity.';
comment on column v3.attempts.effects is 'none, practice_only or review_state: what the graded answer changed.';
comment on column v3.attempts.grader is 'Evaluator that graded the answer, for audit.';

-- 2. review_events: the Attempt, not an Assessment, is the idempotency identity ---------------------------------

alter table v3.review_events drop constraint if exists review_events_assessment_fk;
alter table v3.review_events alter column assessment_id drop not null;
alter table v3.review_events drop constraint if exists review_events_assessment_authoritative_unique;

create unique index if not exists review_events_attempt_unique
  on v3.review_events (attempt_id) where attempt_id is not null;

comment on column v3.review_events.assessment_id is
  'Legacy (before B4.2): the Assessment of the event. Null for new events; dropped in B4.3.';

-- 3. learner_known_concepts keeps the Attempt that proved the word ----------------------------------------------

alter table v3.learner_known_concepts
  add column if not exists attempt_id uuid references v3.attempts(id) on delete set null;

-- 4. The one-step graded answer ---------------------------------------------------------------------------------

create or replace function v3.submit_graded_attempt(p_payload jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = ''
set lock_timeout = '3s'
set statement_timeout = '10s'
as $$
declare
  v_user_id uuid := (p_payload->>'user_id')::uuid;
  v_activity_id uuid := (p_payload->>'activity_id')::uuid;
  v_submission_id uuid := (p_payload->>'submission_id')::uuid;
  v_response jsonb := p_payload->'response_payload';
  v_outcome text := p_payload->>'outcome';
  v_score numeric := (p_payload->>'score')::numeric;
  v_effects text := p_payload->>'effects';
  v_review jsonb := nullif(p_payload->'review_transition', 'null'::jsonb);
  v_event jsonb := nullif(p_payload->'target_event', 'null'::jsonb);
  v_activity v3.session_activities;
  v_session v3.learning_sessions;
  v_attempt v3.attempts;
  v_initial jsonb;
  v_target jsonb;
  v_expected integer;
  v_number integer;
  v_rows integer;
begin
  -- A null anywhere makes the whole condition null, which coalesce turns into "invalid".
  if not coalesce(
       v_user_id is not null and v_activity_id is not null and v_submission_id is not null
       and v_response is not null and jsonb_typeof(v_response) = 'object'
       and v_outcome in ('correct', 'incorrect') and v_score in (0, 1)
       and (v_outcome = 'correct') = (v_score = 1)
       and v_effects in ('none', 'practice_only', 'review_state')
       and (v_effects = 'review_state') = (v_review is not null),
       false) then
    raise exception using errcode = '22023', message = 'invalid_submission';
  end if;

  -- Ownership first, under the activity row lock a skip also takes (no existence oracle).
  select a.* into v_activity
    from v3.session_activities a
    join v3.learning_sessions s on s.id = a.session_id
   where a.id = v_activity_id and s.user_id = v_user_id
   for update of a;
  if not found then
    raise exception using errcode = 'P0002', message = 'activity_not_found';
  end if;
  select * into v_session from v3.learning_sessions where id = v_activity.session_id;

  select * into v_attempt from v3.attempts where user_id = v_user_id and submission_id = v_submission_id;
  if found then
    if v_attempt.activity_id <> v_activity_id or v_attempt.response_payload is distinct from v_response
       or v_attempt.graded_at is null then
      raise exception using errcode = '23505', message = 'submission_conflict';
    end if;
    return jsonb_build_object('status', 'reused', 'attempt_id', v_attempt.id,
      'outcome', v_attempt.outcome, 'score', v_attempt.score, 'effects', v_attempt.effects);
  end if;

  if exists (select 1 from v3.attempts
              where activity_id = v_activity_id and user_id = v_user_id and graded_at is not null) then
    raise exception using errcode = '23505', message = 'activity_answered';
  end if;
  if v_activity.status is distinct from 'active'::v3.activity_status then
    raise exception using errcode = '55000', message = 'activity_closed';
  end if;

  select coalesce(max(attempt_number), 0) + 1 into v_number from v3.attempts
   where activity_id = v_activity_id and user_id = v_user_id;
  -- The caller may name the new Attempt (its ladder event key and ReviewEvent refer to it before the insert).
  insert into v3.attempts (
    id, activity_id, user_id, submission_id, attempt_number, status, response_payload,
    started_at, submitted_at, duration_ms, client_metadata,
    outcome, score, graded_at, effects, grader
  ) values (
    coalesce(nullif(p_payload->>'attempt_id', '')::uuid, extensions.gen_random_uuid()), v_activity_id, v_user_id, v_submission_id, v_number, 'submitted', v_response,
    nullif(p_payload->>'started_at', '')::timestamptz,
    coalesce(nullif(p_payload->>'submitted_at', '')::timestamptz, now()),
    nullif(p_payload->>'duration_ms', '')::integer,
    coalesce(p_payload->'client_metadata', '{}'::jsonb),
    v_outcome, v_score, now(), v_effects, p_payload->>'grader'
  ) on conflict (user_id, submission_id) do nothing returning * into v_attempt;
  if not found then
    -- The same key was stored meanwhile for another activity: the activity row lock does not serialize that.
    raise exception using errcode = '23505', message = 'submission_conflict';
  end if;

  if v_review is not null then
    v_target := v_review->'review_state';
    v_initial := v_review->'initial_review_state';
    v_expected := (v_review->>'expected_review_state_version')::integer;

    if v_initial is not null then
      if v_expected <> 0
         or v_initial->>'fsrs_state' <> 'new'
         or (v_initial->>'version')::integer <> 0
         or (v_initial->>'reps')::integer <> 0
         or (v_initial->>'lapses')::integer <> 0
         or v_initial->>'user_id' <> v_user_id::text
         or v_initial->>'id' <> v_target->>'id'
         or v_initial->>'concept_id' <> v_target->>'concept_id'
         or v_initial->>'review_mode' <> v_target->>'review_mode'
         or (v_review->'review_event')->>'review_state_id' <> v_initial->>'id'
         or (v_initial->>'due_at')::timestamptz > now() + interval '5 minutes'
         or (v_initial->>'due_at')::timestamptz < now() - interval '5 minutes' then
        raise exception 'graded_attempt_conflict: initial_review_state';
      end if;
      if not (
        v_session.type = 'practice'
        and v_session.goal->>'origin' in ('known_check', 'example_practice', 'quick_review')
        and v_activity.review_origin = false
        and v_activity.concept_id = (v_initial->>'concept_id')::uuid
        and (
          (v_activity.activity_type = 'mcq' and v_initial->>'review_mode' = 'concept_to_meaning')
          or (v_activity.activity_type = 'cloze' and v_initial->>'review_mode' = 'meaning_to_concept')
          or (v_activity.activity_type = 'dictation' and v_initial->>'review_mode' = 'audio_to_text')
        )
      ) then
        raise exception 'graded_attempt_conflict: initial_review_provenance';
      end if;
      insert into v3.review_states (id, user_id, concept_id, review_mode, fsrs_state, due_at, version)
      values ((v_initial->>'id')::uuid, v_user_id, (v_initial->>'concept_id')::uuid,
              (v_initial->>'review_mode')::v3.review_mode, 'new', (v_initial->>'due_at')::timestamptz, 0)
      on conflict (user_id, concept_id, review_mode) do nothing;
      get diagnostics v_rows = row_count;
      if v_rows <> 1 then
        raise exception 'graded_attempt_conflict: review_state';
      end if;
    end if;

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
       and version = v_expected;
    get diagnostics v_rows = row_count;
    if v_rows <> 1 then
      raise exception 'graded_attempt_conflict: review_state';
    end if;

    insert into v3.review_events (
      review_state_id, attempt_id, review_mode, rating, provenance,
      previous_scheduling_state, resulting_scheduling_state, reviewed_at
    ) values (
      ((v_review->'review_event')->>'review_state_id')::uuid,
      v_attempt.id,
      ((v_review->'review_event')->>'review_mode')::v3.review_mode,
      ((v_review->'review_event')->>'rating')::integer,
      (v_review->'review_event')->>'provenance',
      (v_review->'review_event')->'previous_scheduling_state',
      (v_review->'review_event')->'resulting_scheduling_state',
      ((v_review->'review_event')->>'reviewed_at')::timestamptz
    );
  end if;

  if v_event is not null then
    if v_activity.concept_id is not null and (v_event->>'concept_id')::uuid <> v_activity.concept_id then
      raise exception 'graded_attempt_conflict: target_event';
    end if;
    insert into v3.target_events (user_id, concept_id, kind, outcome, event_key, occurred_at)
    values (v_user_id, (v_event->>'concept_id')::uuid, v_event->>'kind', v_event->>'outcome',
            v_event->>'event_key', now())
    on conflict (user_id, event_key) do nothing;
  end if;

  return jsonb_build_object('status', 'created', 'attempt_id', v_attempt.id,
    'outcome', v_outcome, 'score', v_score, 'effects', v_effects);
end;
$$;

revoke all on function v3.submit_graded_attempt(jsonb) from public, anon, authenticated;
grant execute on function v3.submit_graded_attempt(jsonb) to service_role;

comment on function v3.submit_graded_attempt(jsonb) is
  'B4.2: stores one graded Attempt with its ReviewState/ReviewEvent change and optional ladder event atomically. '
  'Grading and FSRS math are computed in Python; the first graded Attempt closes the activity.';

-- 5. Readers move from applied Assessments to graded Attempts ---------------------------------------------------

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
  -- Each activity counts once, by its latest graded Attempt (the first one closes it), or by the latest applied
  -- Assessment of a legacy Attempt that was never graded.
  select count(*), max(latest.attempt_id::text)::uuid into v_passed, v_attempt_id
  from (
    select distinct on (sa.id) sa.id, t.id as attempt_id, coalesce(t.score, a.overall_score) as score
    from v3.session_activities sa
    join v3.attempts t on t.activity_id = sa.id and t.user_id = p_user_id
    left join v3.assessments a on a.attempt_id = t.id and t.graded_at is null
    left join v3.assessment_applications aa on aa.assessment_id = a.id and aa.user_id = p_user_id
    where sa.session_id = v_session.id and (t.graded_at is not null or aa.id is not null)
    order by sa.id, coalesce(t.graded_at, aa.applied_at) desc
  ) latest
  where latest.score >= 1;

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
      where t.activity_id = a.id and t.user_id = p_user_id
        and (t.graded_at is not null
             or exists (select 1 from v3.assessment_applications ap where ap.attempt_id = t.id and ap.user_id = p_user_id))
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
       where a.session_id = v_session.id and t.user_id = p_user_id
         and (t.graded_at is not null
              or exists (select 1 from v3.assessment_applications ap where ap.attempt_id = t.id and ap.user_id = p_user_id))),
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
