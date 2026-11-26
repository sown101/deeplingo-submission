-- DeepLingo v3 migration 031: assessment application transaction boundary.

alter table v3.concept_mastery
  add column if not exists version integer not null default 0;

alter table v3.learner_skill_states
  add column if not exists version integer not null default 0;

alter table v3.review_states
  add column if not exists version integer not null default 0;

alter table v3.concept_mastery
  add constraint concept_mastery_version_chk check (version >= 0);

alter table v3.learner_skill_states
  add constraint learner_skill_states_version_chk check (version >= 0);

alter table v3.review_states
  add constraint review_states_version_chk check (version >= 0);

create table if not exists v3.assessment_applications (
  id uuid primary key default extensions.gen_random_uuid(),
  assessment_id uuid not null references v3.assessments(id) on delete cascade,
  attempt_id uuid not null references v3.attempts(id) on delete cascade,
  user_id uuid not null references v3.profiles(id) on delete cascade,
  status text not null default 'applied',
  metadata jsonb not null default '{}'::jsonb,
  applied_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint assessment_applications_assessment_unique unique (assessment_id),
  constraint assessment_applications_status_chk check (status = 'applied'),
  constraint assessment_applications_metadata_object_chk check (jsonb_typeof(metadata) = 'object')
);

alter table v3.assessment_applications enable row level security;

grant select on v3.assessment_applications to authenticated;
grant all privileges on v3.assessment_applications to service_role;

create policy "Users can read own assessment applications"
  on v3.assessment_applications for select
  to authenticated
  using ((select auth.uid()) = user_id);

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
  v_mastery jsonb := p_payload->'mastery';
  v_skill jsonb;
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

  if v_mastery is not null then
    v_target := v_mastery->'target';
    if v_mastery ? 'expected_version' and jsonb_typeof(v_mastery->'expected_version') <> 'null' then
      v_expected_version := (v_mastery->>'expected_version')::integer;
      update v3.concept_mastery
      set recognition = (v_target->>'recognition')::numeric,
          comprehension = (v_target->>'comprehension')::numeric,
          listening = (v_target->>'listening')::numeric,
          recall = (v_target->>'recall')::numeric,
          production = (v_target->>'production')::numeric,
          speaking = (v_target->>'speaking')::numeric,
          overall = (v_target->>'overall')::numeric,
          confidence = (v_target->>'confidence')::numeric,
          state = (v_target->>'state')::v3.mastery_state,
          sample_count = (v_target->>'sample_count')::integer,
          version = (v_target->>'version')::integer,
          last_seen_at = nullif(v_target->>'last_seen_at', '')::timestamptz,
          last_assessed_at = nullif(v_target->>'last_assessed_at', '')::timestamptz,
          updated_at = now()
      where user_id = v_user_id
        and concept_id = (v_target->>'concept_id')::uuid
        and version = v_expected_version;
      get diagnostics v_row_count = row_count;
      if v_row_count <> 1 then
        raise exception 'assessment_application_conflict: concept_mastery';
      end if;
    else
      insert into v3.concept_mastery (
        user_id, concept_id, recognition, comprehension, listening, recall, production, speaking,
        overall, confidence, state, sample_count, version, last_seen_at, last_assessed_at
      )
      values (
        v_user_id,
        (v_target->>'concept_id')::uuid,
        (v_target->>'recognition')::numeric,
        (v_target->>'comprehension')::numeric,
        (v_target->>'listening')::numeric,
        (v_target->>'recall')::numeric,
        (v_target->>'production')::numeric,
        (v_target->>'speaking')::numeric,
        (v_target->>'overall')::numeric,
        (v_target->>'confidence')::numeric,
        (v_target->>'state')::v3.mastery_state,
        (v_target->>'sample_count')::integer,
        (v_target->>'version')::integer,
        nullif(v_target->>'last_seen_at', '')::timestamptz,
        nullif(v_target->>'last_assessed_at', '')::timestamptz
      )
      on conflict (user_id, concept_id) do nothing;
      get diagnostics v_row_count = row_count;
      if v_row_count <> 1 then
        raise exception 'assessment_application_conflict: concept_mastery';
      end if;
    end if;
  end if;

  for v_skill in select value from jsonb_array_elements(coalesce(p_payload->'skill_states', '[]'::jsonb))
  loop
    v_target := v_skill->'target';
    if v_skill ? 'expected_version' and jsonb_typeof(v_skill->'expected_version') <> 'null' then
      v_expected_version := (v_skill->>'expected_version')::integer;
      update v3.learner_skill_states
      set score = (v_target->>'score')::numeric,
          confidence = (v_target->>'confidence')::numeric,
          sample_count = (v_target->>'sample_count')::integer,
          version = (v_target->>'version')::integer,
          updated_at = now()
      where user_id = v_user_id
        and language_code = v_target->>'language_code'
        and skill = (v_target->>'skill')::v3.skill_type
        and version = v_expected_version;
      get diagnostics v_row_count = row_count;
      if v_row_count <> 1 then
        raise exception 'assessment_application_conflict: learner_skill_state';
      end if;
    else
      insert into v3.learner_skill_states (
        user_id, language_code, skill, score, confidence, sample_count, version
      )
      values (
        v_user_id,
        v_target->>'language_code',
        (v_target->>'skill')::v3.skill_type,
        (v_target->>'score')::numeric,
        (v_target->>'confidence')::numeric,
        (v_target->>'sample_count')::integer,
        (v_target->>'version')::integer
      )
      on conflict (user_id, language_code, skill) do nothing;
      get diagnostics v_row_count = row_count;
      if v_row_count <> 1 then
        raise exception 'assessment_application_conflict: learner_skill_state';
      end if;
    end if;
  end loop;

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

revoke all on function v3.apply_assessment_application(jsonb) from public;
grant execute on function v3.apply_assessment_application(jsonb) to service_role;

comment on table v3.assessment_applications is
  'Durable idempotency marker for one atomic learner-state application per authoritative Assessment.';

comment on function v3.apply_assessment_application(jsonb) is
  'Atomic persistence boundary for server-computed assessment effects. FSRS and learning policy are computed in Python.';
