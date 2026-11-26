-- ADR-020 section 7: practice a saved word from an example sentence ("choose the meaning").
--
-- A session with origin `example_practice` holds one fully materialized MCQ whose answer key
-- is the dictionary sense of the saved word, so it is valid for every example source,
-- generated included. The activity is grounded to an ExampleSentence instead of a
-- LearningObject. The server builds the payloads; this RPC only checks that the learner saved
-- the word, that the example belongs to it and that the payloads are well formed, then
-- commits the session and its activity atomically. It never marks a word known and never
-- writes mastery or review (those come from the normal assessment application).
-- Forward-only.

alter table v3.session_activities
  add column if not exists example_sentence_id uuid references v3.example_sentences(id) on delete set null;
alter table v3.session_activities drop constraint if exists session_activities_one_source_chk;
alter table v3.session_activities add constraint session_activities_one_source_chk
  check (example_sentence_id is null or learning_object_id is null);
create index if not exists session_activities_example_sentence_idx
  on v3.session_activities (example_sentence_id);

-- The materialization guard keeps the new identity column immutable too.
create or replace function v3.guard_materialized_activity_payload()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.prompt_payload <> '{}'::jsonb or old.expected_response_payload is not null then
    if new.prompt_payload is distinct from old.prompt_payload
       or new.expected_response_payload is distinct from old.expected_response_payload
       or new.id is distinct from old.id
       or new.session_id is distinct from old.session_id
       or new.activity_type is distinct from old.activity_type
       or new.concept_id is distinct from old.concept_id
       or new.learning_object_id is distinct from old.learning_object_id
       or (old.example_sentence_id is not null and new.example_sentence_id is distinct from old.example_sentence_id)
       or new.position is distinct from old.position
       or new.review_origin is distinct from old.review_origin
       or new.review_mode is distinct from old.review_mode
       or new.review_state_id is distinct from old.review_state_id
       or new.review_provenance_version is distinct from old.review_provenance_version
       or new.source_review_state_version is distinct from old.source_review_state_version then
      raise exception 'activity_materialization_conflict: immutable_payload_or_identity' using errcode = '23514';
    end if;
  end if;
  return new;
end;
$$;

create unique index if not exists learning_sessions_one_active_example_practice_idx
  on v3.learning_sessions (user_id, (goal->>'concept_id'))
  where type = 'practice'
    and status in ('planned', 'active')
    and goal->>'origin' = 'example_practice';

create or replace function v3.start_or_resume_example_practice_session(
  p_user_id uuid,
  p_concept_id uuid,
  p_example_sentence_id uuid,
  p_language_code text,
  p_support_language_code text,
  p_policy_version text,
  p_prompt_payload jsonb,
  p_expected_response_payload jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_session v3.learning_sessions;
begin
  if p_policy_version <> 'adr020-example-practice-v1'
      or jsonb_typeof(p_prompt_payload) <> 'object'
      or jsonb_typeof(p_expected_response_payload) <> 'object'
      or p_prompt_payload->>'activity_kind' <> 'mcq'
      or jsonb_typeof(p_prompt_payload->'options') <> 'array'
      or jsonb_array_length(p_prompt_payload->'options') <> 4
      or not (p_prompt_payload->'options') @> to_jsonb(p_expected_response_payload->>'correct_option') then
    raise exception 'example_practice_conflict: invalid_payload';
  end if;
  -- The learner saved the word, and the example belongs to it and to its language.
  if not exists (select 1 from v3.saved_concepts sc where sc.user_id = p_user_id and sc.concept_id = p_concept_id)
      or not exists (
        select 1 from v3.example_sentences e
        join v3.concepts c on c.id = e.concept_id
        where e.id = p_example_sentence_id and e.concept_id = p_concept_id
          and c.language_code = p_language_code and e.language_code = p_language_code
      )
      or not exists (
        select 1 from v3.user_language_preferences up
        where up.user_id = p_user_id and up.language_code = p_language_code
          and up.support_language_code = p_support_language_code
      ) then
    raise exception 'example_practice_conflict: word_example_or_language';
  end if;

  select * into v_session from v3.learning_sessions
  where user_id = p_user_id and type = 'practice'
    and status in ('planned', 'active')
    and goal->>'origin' = 'example_practice'
    and goal->>'concept_id' = p_concept_id::text
  order by created_at limit 1;
  if v_session.id is not null then
    if v_session.goal->>'example_sentence_id' = p_example_sentence_id::text
        and v_session.goal->>'support_language_code' = p_support_language_code then
      return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
    end if;
    -- A session on another example of the same word is replaced, never merged.
    update v3.learning_sessions set status = 'abandoned', updated_at = now()
    where id = v_session.id;
  end if;

  insert into v3.learning_sessions (
    user_id, language_code, type, status, goal, started_at
  ) values (
    p_user_id, p_language_code, 'practice', 'active',
    jsonb_build_object(
      'origin', 'example_practice',
      'session_policy_version', p_policy_version,
      'concept_id', p_concept_id,
      'example_sentence_id', p_example_sentence_id,
      'support_language_code', p_support_language_code,
      'materialization', 'eager',
      'max_activities', 1
    ), now()
  ) returning * into v_session;

  insert into v3.session_activities (
    session_id, concept_id, learning_object_id, example_sentence_id, activity_type, position,
    review_origin, prompt_payload, expected_response_payload, status
  ) values (
    v_session.id, p_concept_id, null, p_example_sentence_id, 'mcq'::v3.activity_type, 1,
    false, p_prompt_payload, p_expected_response_payload, 'active'
  );

  return jsonb_build_object('created', true, 'session', to_jsonb(v_session));
exception
  when unique_violation then
    select * into v_session from v3.learning_sessions
    where user_id = p_user_id and type = 'practice'
      and status in ('planned', 'active')
      and goal->>'origin' = 'example_practice'
      and goal->>'concept_id' = p_concept_id::text
    order by created_at limit 1;
    if v_session.id is not null
        and v_session.goal->>'example_sentence_id' = p_example_sentence_id::text
        and v_session.goal->>'support_language_code' = p_support_language_code then
      return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
    end if;
    raise;
end;
$$;

revoke all on function v3.start_or_resume_example_practice_session(
  uuid, uuid, uuid, text, text, text, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function v3.start_or_resume_example_practice_session(
  uuid, uuid, uuid, text, text, text, jsonb, jsonb
) to service_role;

-- The first Evidence of an example practice may create the Concept's first ReviewState, as
-- video learning and known checks do. Same function with the origin widened.
create or replace function v3.apply_first_video_learning_assessment(p_payload jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_initial jsonb := p_payload->'review_transition'->'initial_review_state';
  v_target jsonb := p_payload->'review_transition'->'review_state';
  v_user_id uuid := (p_payload->>'user_id')::uuid;
  v_assessment_id uuid := (p_payload->>'assessment_id')::uuid;
  v_attempt_id uuid := (p_payload->>'attempt_id')::uuid;
  v_state_id uuid := (v_initial->>'id')::uuid;
  v_existing_application uuid;
  v_row_count integer;
begin
  select id into v_existing_application
  from v3.assessment_applications where assessment_id = v_assessment_id;
  if v_existing_application is not null then
    return jsonb_build_object(
      'status', 'reused', 'assessment_id', v_assessment_id,
      'application_id', v_existing_application,
      'metadata', jsonb_build_object('application', 'already_applied')
    );
  end if;

  if v_initial is null or v_target is null
      or (p_payload->'review_transition'->>'expected_review_state_version')::integer <> 0
      or v_initial->>'fsrs_state' <> 'new'
      or (v_initial->>'version')::integer <> 0
      or (v_initial->>'reps')::integer <> 0
      or (v_initial->>'lapses')::integer <> 0
      or v_initial->>'user_id' <> v_user_id::text
      or v_initial->>'id' <> v_target->>'id'
      or v_initial->>'concept_id' <> v_target->>'concept_id'
      or v_initial->>'review_mode' <> v_target->>'review_mode'
      or (p_payload->'review_transition'->'review_event')->>'review_state_id' <> v_initial->>'id'
      or (v_initial->>'due_at')::timestamptz > now() + interval '5 minutes'
      or (v_initial->>'due_at')::timestamptz < now() - interval '5 minutes' then
    raise exception 'assessment_application_conflict: initial_review_state';
  end if;

  if not exists (
    select 1
    from v3.assessments a
    join v3.attempts t on t.id = a.attempt_id
    join v3.session_activities sa on sa.id = t.activity_id
    join v3.learning_sessions ls on ls.id = sa.session_id
    where a.id = v_assessment_id and t.id = v_attempt_id
      and t.user_id = v_user_id and ls.user_id = v_user_id
      and ls.type = 'practice' and ls.goal->>'origin' in ('video_learning', 'known_check', 'example_practice')
      and sa.review_origin = false
      and sa.concept_id = (v_initial->>'concept_id')::uuid
      and (
        (sa.activity_type = 'mcq' and v_initial->>'review_mode' = 'concept_to_meaning')
        or (sa.activity_type = 'cloze' and v_initial->>'review_mode' = 'meaning_to_concept')
        or (sa.activity_type = 'dictation' and v_initial->>'review_mode' = 'audio_to_text')
      )
  ) then
    raise exception 'assessment_application_conflict: initial_review_provenance';
  end if;

  insert into v3.review_states (
    id, user_id, concept_id, review_mode, fsrs_state, due_at, version
  ) values (
    v_state_id, v_user_id, (v_initial->>'concept_id')::uuid,
    (v_initial->>'review_mode')::v3.review_mode,
    'new', (v_initial->>'due_at')::timestamptz, 0
  ) on conflict (user_id, concept_id, review_mode) do nothing;
  get diagnostics v_row_count = row_count;
  if v_row_count <> 1 then
    raise exception 'assessment_application_conflict: review_state';
  end if;

  return v3.apply_assessment_application(p_payload);
end;
$$;

revoke all on function v3.apply_first_video_learning_assessment(jsonb)
  from public, anon, authenticated;
grant execute on function v3.apply_first_video_learning_assessment(jsonb)
  to service_role;
