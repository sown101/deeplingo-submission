-- A24 (M1 D2, owner decision 2026-10-20): example practice stores its MCQ answer key as the option
-- index, the value the learner submits (`selected_option: <int>`), like Quick review. Policy
-- `adr020-example-practice-v1` stored the meaning text, so every real answer was graded wrong.
-- Forward-only: only the start RPC changes.
--
-- 1. The RPC accepts policy `adr020-example-practice-v2` only, with `correct_option` an integer
--    index into the four options.
-- 2. An open session of another policy (a v1 text key) is never resumed: it is abandoned and a new
--    v2 session is started, so no new answer is graded against a text key.
-- Attempts and Assessments already stored under v1 are left as they are (no rewrite of learner state).

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
  if p_policy_version <> 'adr020-example-practice-v2'
      or jsonb_typeof(p_prompt_payload) <> 'object'
      or jsonb_typeof(p_expected_response_payload) <> 'object'
      or p_prompt_payload->>'activity_kind' <> 'mcq'
      or jsonb_typeof(p_prompt_payload->'options') <> 'array'
      or jsonb_array_length(p_prompt_payload->'options') <> 4
      or jsonb_typeof(p_expected_response_payload->'correct_option') <> 'number'
      or (p_expected_response_payload->>'correct_option') !~ '^[0-3]$' then
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
        and v_session.goal->>'support_language_code' = p_support_language_code
        and v_session.goal->>'session_policy_version' = p_policy_version then
      return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
    end if;
    -- A session on another example, or of an older policy (A24: a text answer key), is replaced,
    -- never merged or resumed.
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
        and v_session.goal->>'support_language_code' = p_support_language_code
        and v_session.goal->>'session_policy_version' = p_policy_version then
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
