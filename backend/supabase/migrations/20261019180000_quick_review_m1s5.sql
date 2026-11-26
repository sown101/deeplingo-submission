-- M1 S5: Quick review, a batch of deterministic "choose the meaning" questions (policy quick_review_v1).
--
-- One practice session (goal.origin = 'quick_review') holds up to 20 pre-built MCQ activities, each
-- grounded to a Concept and one ExampleSentence. A question on a due ReviewState is a review
-- opportunity: the activity records the state and its version (review_origin = true). A question on
-- a saved word without a concept_to_meaning ReviewState is a new card (review_origin = false). The
-- application policy (assessment module) updates only ReviewState, and only for that exact version
-- or a still-missing state; it never writes mastery or skills. Forward-only.

create unique index if not exists learning_sessions_one_active_quick_review_idx
  on v3.learning_sessions (user_id, language_code)
  where type = 'practice' and status in ('planned', 'active') and (goal->>'origin') = 'quick_review';

-- 1. Start or resume. The server built every question; this rechecks ownership, due state,
-- versions and payload shape, and writes the session and its activities in one transaction.
create or replace function v3.start_or_resume_quick_review_session(
  p_user_id uuid, p_language_code text, p_support_language_code text, p_policy_version text, p_items jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_session v3.learning_sessions;
  v_item jsonb;
  v_position integer := 0;
  v_concept uuid;
  v_example uuid;
  v_state v3.review_states;
begin
  select * into v_session from v3.learning_sessions
  where user_id = p_user_id and language_code = p_language_code and type = 'practice'
    and status in ('planned', 'active') and goal->>'origin' = 'quick_review'
  order by created_at limit 1;
  if v_session.id is not null then
    return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
  end if;

  if p_policy_version <> 'quick_review_v1'
      or jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) < 1 or jsonb_array_length(p_items) > 20
      or (select count(distinct value->>'concept_id') from jsonb_array_elements(p_items)) <> jsonb_array_length(p_items) then
    raise exception 'quick_review_conflict: invalid_batch';
  end if;
  if not exists (
    select 1 from v3.user_language_preferences up
    where up.user_id = p_user_id and up.language_code = p_language_code
      and up.support_language_code = p_support_language_code
  ) then
    raise exception 'quick_review_conflict: language';
  end if;

  for v_item in select value from jsonb_array_elements(p_items) loop
    v_concept := (v_item->>'concept_id')::uuid;
    v_example := (v_item->>'example_sentence_id')::uuid;
    if jsonb_typeof(v_item->'prompt_payload') <> 'object'
        or jsonb_typeof(v_item->'expected_response_payload') <> 'object'
        or v_item->'prompt_payload'->>'activity_kind' <> 'mcq'
        or jsonb_typeof(v_item->'prompt_payload'->'options') <> 'array'
        or jsonb_array_length(v_item->'prompt_payload'->'options') <> 4
        or jsonb_typeof(v_item->'expected_response_payload'->'correct_option') <> 'number'
        or (v_item->'expected_response_payload'->>'correct_option')::numeric not in (0, 1, 2)
        or v_item->'prompt_payload'->'options'->>3 <> 'Không nhớ'
        or v_item->'prompt_payload'->'_materialization'->'provenance'->>'source_example_sentence_id' <> v_example::text
        or v_item->'prompt_payload'->'_materialization'->'provenance'->>'source_concept_id' <> v_concept::text then
      raise exception 'quick_review_conflict: invalid_payload';
    end if;
    if not exists (
      select 1 from v3.example_sentences e join v3.concepts c on c.id = e.concept_id
      where e.id = v_example and e.concept_id = v_concept
        and c.language_code = p_language_code and e.language_code = p_language_code
    ) then
      raise exception 'quick_review_conflict: word_or_example';
    end if;

    if jsonb_typeof(v_item->'review_state_id') = 'string' then
      -- A review opportunity: the learner's own due state, at the version the question was built for.
      select * into v_state from v3.review_states
      where id = (v_item->>'review_state_id')::uuid and user_id = p_user_id and concept_id = v_concept
        and review_mode = 'concept_to_meaning';
      if v_state.id is null or v_state.version <> (v_item->>'source_review_state_version')::integer
          or v_state.due_at > now() then
        raise exception 'quick_review_conflict: review_state';
      end if;
    else
      -- A new card: a saved, not known word with no concept_to_meaning state yet.
      if not exists (select 1 from v3.saved_concepts sc where sc.user_id = p_user_id and sc.concept_id = v_concept)
          or exists (select 1 from v3.learner_known_concepts k where k.user_id = p_user_id and k.concept_id = v_concept)
          or exists (select 1 from v3.review_states rs where rs.user_id = p_user_id and rs.concept_id = v_concept
                     and rs.review_mode = 'concept_to_meaning') then
        raise exception 'quick_review_conflict: new_word';
      end if;
      v_state := null;
    end if;
  end loop;

  insert into v3.learning_sessions (user_id, language_code, type, status, goal, started_at)
  values (p_user_id, p_language_code, 'practice', 'active', jsonb_build_object(
    'origin', 'quick_review', 'session_policy_version', p_policy_version,
    'support_language_code', p_support_language_code, 'materialization', 'eager',
    'max_activities', jsonb_array_length(p_items)
  ), now()) returning * into v_session;

  for v_item in select value from jsonb_array_elements(p_items) loop
    v_position := v_position + 1;
    insert into v3.session_activities (
      session_id, concept_id, learning_object_id, example_sentence_id, activity_type, position,
      review_origin, review_mode, review_state_id, source_review_state_version, review_provenance_version,
      prompt_payload, expected_response_payload, status
    ) values (
      v_session.id, (v_item->>'concept_id')::uuid, null, (v_item->>'example_sentence_id')::uuid,
      'mcq'::v3.activity_type, v_position,
      jsonb_typeof(v_item->'review_state_id') = 'string',
      case when jsonb_typeof(v_item->'review_state_id') = 'string' then 'concept_to_meaning'::v3.review_mode end,
      case when jsonb_typeof(v_item->'review_state_id') = 'string' then (v_item->>'review_state_id')::uuid end,
      case when jsonb_typeof(v_item->'review_state_id') = 'string'
           then (v_item->>'source_review_state_version')::integer end,
      case when jsonb_typeof(v_item->'review_state_id') = 'string' then 'quick-review-provenance-v1' end,
      v_item->'prompt_payload', v_item->'expected_response_payload', 'active'
    );
  end loop;

  return jsonb_build_object('created', true, 'session', to_jsonb(v_session));
exception
  when unique_violation then
    select * into v_session from v3.learning_sessions
    where user_id = p_user_id and language_code = p_language_code and type = 'practice'
      and status in ('planned', 'active') and goal->>'origin' = 'quick_review'
    order by created_at limit 1;
    if v_session.id is not null then
      return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
    end if;
    raise;
end $$;

revoke all on function v3.start_or_resume_quick_review_session(uuid, text, text, text, jsonb)
  from public, anon, authenticated;
grant execute on function v3.start_or_resume_quick_review_session(uuid, text, text, text, jsonb) to service_role;

-- 2. A new card from Quick review may create the Concept's first concept_to_meaning ReviewState,
-- as video learning, known checks and example practice do. Same function with the origin widened.
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
      and ls.type = 'practice' and ls.goal->>'origin' in ('video_learning', 'known_check', 'example_practice', 'quick_review')
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
