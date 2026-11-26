-- FR-5.3: deterministic cloze batches, using the existing atomic session RPC.
-- Draft only: applying this migration requires separate owner approval.
-- No tables, policies, grants or function signatures change.

create or replace function v3.start_or_resume_quick_review_session(
  p_user_id uuid, p_language_code text, p_support_language_code text, p_policy_version text, p_items jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $fn$
declare
  v_session v3.learning_sessions;
  v_item jsonb;
  v_prov jsonb;
  v_position integer := 0;
  v_concept uuid;
  v_example uuid;
  v_object uuid;
  v_meaning_form boolean;
  v_kind text;
  v_mode v3.review_mode;
  v_state v3.review_states;
begin
  select * into v_session from v3.learning_sessions
  where user_id = p_user_id and language_code = p_language_code and type = 'practice'
    and status in ('planned', 'active') and goal->>'origin' = 'quick_review'
  order by created_at limit 1;
  if v_session.id is not null then
    return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
  end if;

  if coalesce(p_policy_version <> 'quick_review_v1'
      or jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) < 1 or jsonb_array_length(p_items) > 20
      or (select count(distinct value->>'concept_id') from jsonb_array_elements(p_items)) <> jsonb_array_length(p_items),
      true) then
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
    v_example := case when jsonb_typeof(v_item->'example_sentence_id') = 'string'
                      then (v_item->>'example_sentence_id')::uuid end;
    v_object := case when jsonb_typeof(v_item->'learning_object_id') = 'string'
                     then (v_item->>'learning_object_id')::uuid end;
    v_prov := v_item->'prompt_payload'->'_materialization'->'provenance';
    v_meaning_form := coalesce(v_prov->>'question_form' = 'meaning', false);
    v_kind := v_item->'prompt_payload'->>'activity_kind';
    v_mode := case when v_kind = 'cloze' then 'meaning_to_concept'::v3.review_mode
                   else 'concept_to_meaning'::v3.review_mode end;
    -- Meaning alone has no sentence; meaning-in-sentence and cloze have exactly one. Missing fields fail.
    if coalesce(
        (v_meaning_form and (v_example is not null or v_object is not null))
        or (not v_meaning_form and (v_example is null) = (v_object is null))
        or coalesce(v_prov->>'question_form', '') not in ('meaning', 'meaning_in_sentence', 'cloze_in_sentence')
        or coalesce(v_kind, '') not in ('mcq', 'cloze')
        or (v_kind = 'mcq' and v_prov->>'question_form' = 'cloze_in_sentence')
        or (v_kind = 'cloze' and v_prov->>'question_form' <> 'cloze_in_sentence')
        or jsonb_typeof(v_item->'prompt_payload') <> 'object'
        or jsonb_typeof(v_item->'expected_response_payload') <> 'object'
        or v_prov->>'source_concept_id' <> v_concept::text
        or (v_prov->>'source_example_sentence_id') is distinct from v_example::text
        or (v_prov->>'source_learning_object_id') is distinct from v_object::text,
        true) then
      raise exception 'quick_review_conflict: invalid_payload';
    end if;
    if v_kind = 'mcq' then
      if coalesce(
          jsonb_typeof(v_item->'prompt_payload'->'options') <> 'array'
          or jsonb_array_length(v_item->'prompt_payload'->'options') <> 4
          or jsonb_typeof(v_item->'expected_response_payload'->'correct_option') <> 'number'
          or (v_item->'expected_response_payload'->>'correct_option')::numeric not in (0, 1, 2)
          or v_item->'prompt_payload'->'options'->>3 <> 'Không nhớ', true) then
        raise exception 'quick_review_conflict: invalid_payload';
      end if;
    else
      if coalesce(
          jsonb_typeof(v_item->'prompt_payload'->'cloze_text') <> 'string'
          or length(v_item->'prompt_payload'->>'cloze_text')
             - length(replace(v_item->'prompt_payload'->>'cloze_text', '______', '')) <> 6
          or jsonb_typeof(v_item->'expected_response_payload'->'answer') <> 'string'
          or length(btrim(v_item->'expected_response_payload'->>'answer')) = 0, true) then
        raise exception 'quick_review_conflict: invalid_payload';
      end if;
    end if;
    if not exists (select 1 from v3.concepts c where c.id = v_concept and c.language_code = p_language_code) then
      raise exception 'quick_review_conflict: word_or_example';
    end if;
    if v_example is not null and not exists (
      select 1 from v3.example_sentences e
      where e.id = v_example and e.concept_id = v_concept and e.language_code = p_language_code
    ) then
      raise exception 'quick_review_conflict: word_or_example';
    end if;
    -- A video sentence only from a video in this learner's own Library.
    if v_object is not null and not exists (
      select 1 from v3.learning_objects lo
        join v3.learner_videos lv on lv.video_id = lo.video_id and lv.user_id = p_user_id
      where lo.id = v_object and lo.concept_id = v_concept
    ) then
      raise exception 'quick_review_conflict: word_or_example';
    end if;
    if exists (select 1 from v3.learner_quick_review_skips s where s.user_id = p_user_id and s.concept_id = v_concept) then
      raise exception 'quick_review_conflict: skipped';
    end if;

    if jsonb_typeof(v_item->'review_state_id') = 'string' then
      -- A review opportunity: the learner's own due state, at the version the question was built for.
      select * into v_state from v3.review_states
      where id = (v_item->>'review_state_id')::uuid and user_id = p_user_id and concept_id = v_concept
        and review_mode = v_mode;
      if v_state.id is null or v_state.version is distinct from (v_item->>'source_review_state_version')::integer
          or v_state.due_at > now() then
        raise exception 'quick_review_conflict: review_state';
      end if;
    else
      -- A new card: a saved or recently looked-up, not known word with no state in this question's review mode yet.
      if not (exists (select 1 from v3.saved_concepts sc where sc.user_id = p_user_id and sc.concept_id = v_concept)
              or exists (select 1 from v3.learner_looked_up_concepts l
                         where l.user_id = p_user_id and l.concept_id = v_concept and l.expires_at > now()))
          or exists (select 1 from v3.learner_known_concepts k where k.user_id = p_user_id and k.concept_id = v_concept)
          or exists (select 1 from v3.review_states rs where rs.user_id = p_user_id and rs.concept_id = v_concept
                     and rs.review_mode = v_mode) then
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
    v_kind := v_item->'prompt_payload'->>'activity_kind';
    v_mode := case when v_kind = 'cloze' then 'meaning_to_concept'::v3.review_mode
                   else 'concept_to_meaning'::v3.review_mode end;
    insert into v3.session_activities (
      session_id, concept_id, learning_object_id, example_sentence_id, activity_type, position,
      review_origin, review_mode, review_state_id, source_review_state_version, review_provenance_version,
      prompt_payload, expected_response_payload, status
    ) values (
      v_session.id, (v_item->>'concept_id')::uuid,
      case when jsonb_typeof(v_item->'learning_object_id') = 'string' then (v_item->>'learning_object_id')::uuid end,
      case when jsonb_typeof(v_item->'example_sentence_id') = 'string' then (v_item->>'example_sentence_id')::uuid end,
      v_kind::v3.activity_type, v_position,
      coalesce(jsonb_typeof(v_item->'review_state_id') = 'string', false),
      case when jsonb_typeof(v_item->'review_state_id') = 'string' then v_mode end,
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
end $fn$;
