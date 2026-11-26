-- One active video-learning session per learner and Library video. The
-- original learning_sessions/session_activities tables and IDs are reused.
create unique index learning_sessions_one_active_video_learning_idx
  on v3.learning_sessions (user_id, (goal->>'video_id'))
  where type = 'practice'
    and status in ('planned', 'active')
    and goal->>'origin' = 'video_learning';

create or replace function v3.start_or_resume_video_learning_session(
  p_user_id uuid,
  p_library_item_id uuid,
  p_video_id uuid,
  p_language_code text,
  p_support_language_code text,
  p_policy_version text,
  p_selected jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_session v3.learning_sessions;
  v_item jsonb;
  v_position integer := 0;
  v_learning_object_id uuid;
  v_concept_id uuid;
  v_activity_type v3.activity_type;
  v_enrichment jsonb;
  v_seen_concepts uuid[] := '{}'::uuid[];
  v_seen_types text[] := '{}'::text[];
begin
  if p_policy_version <> 'v6a7-video-learning-v1'
      or jsonb_typeof(p_selected) <> 'array'
      or jsonb_array_length(p_selected) < 1
      or jsonb_array_length(p_selected) > 3 then
    raise exception 'video_learning_conflict: invalid_selection';
  end if;
  if not exists (
    select 1 from v3.learner_videos lv
    join v3.videos v on v.id = lv.video_id
    where lv.id = p_library_item_id and lv.user_id = p_user_id
      and lv.video_id = p_video_id
      and v.original_language_code = p_language_code
      and v.learning_status = 'ready' and v.learning_object_count > 0
      and v.learning_prepared_language_code = p_support_language_code
  ) then
    raise exception 'video_learning_conflict: library_or_readiness';
  end if;

  select * into v_session from v3.learning_sessions
  where user_id = p_user_id and type = 'practice'
    and status in ('planned', 'active')
    and goal->>'origin' = 'video_learning'
    and goal->>'video_id' = p_video_id::text
  order by created_at limit 1;
  if v_session.id is not null then
    if v_session.goal->>'support_language_code' <> p_support_language_code then
      raise exception 'video_learning_conflict: active_language_changed';
    end if;
    return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
  end if;

  -- Validate every server-selected occurrence before any write. This RPC is
  -- service-role only, but still rechecks ownership, source, and enrichment.
  for v_item in select value from jsonb_array_elements(p_selected)
  loop
    v_position := v_position + 1;
    v_learning_object_id := (v_item->>'learning_object_id')::uuid;
    v_concept_id := (v_item->>'concept_id')::uuid;
    v_activity_type := (v_item->>'activity_type')::v3.activity_type;
    if (v_item->>'position')::integer <> v_position
        or v_activity_type not in ('mcq', 'cloze', 'dictation')
        or v_concept_id = any(v_seen_concepts)
        or v_activity_type::text = any(v_seen_types) then
      raise exception 'video_learning_conflict: invalid_selection';
    end if;
    v_seen_concepts := array_append(v_seen_concepts, v_concept_id);
    v_seen_types := array_append(v_seen_types, v_activity_type::text);
    select coalesce(lo.raw_ai_diagnostics->'enrichments'->p_support_language_code,
                    lo.raw_ai_diagnostics->'enrichment')
      into v_enrichment
    from v3.learning_objects lo
    join v3.concepts c on c.id = lo.concept_id
    join v3.transcript_segments s on s.id = lo.transcript_segment_id
    join v3.video_transcripts t on t.id = s.transcript_id
    where lo.id = v_learning_object_id and lo.concept_id = v_concept_id
      and lo.video_id = p_video_id and t.video_id = p_video_id
      and t.is_original = true and t.language_code = p_language_code
      and c.language_code = p_language_code
      and lo.start_codepoint is not null and lo.end_codepoint is not null
      and lo.start_codepoint >= 0 and lo.end_codepoint > lo.start_codepoint
      and substr(s.text, lo.start_codepoint + 1,
                 lo.end_codepoint - lo.start_codepoint) = lo.evidence_text
      and coalesce(lo.raw_ai_diagnostics->'enrichments'->p_support_language_code,
                   lo.raw_ai_diagnostics->'enrichment')->>'concept_sense_key' = c.sense_key
    limit 1;
    if v_enrichment is null
        or v_enrichment->>'concept_id' <> v_concept_id::text
        or v_enrichment->>'source_language_code' <> p_language_code
        or v_enrichment->>'target_language_code' <> p_support_language_code
        or btrim(coalesce(v_enrichment->>'contextual_meaning', '')) = ''
        or btrim(coalesce(v_enrichment->>'explanation', '')) = '' then
      raise exception 'video_learning_conflict: unprepared_occurrence';
    end if;
  end loop;

  insert into v3.learning_sessions (
    user_id, language_code, type, status, goal, started_at
  ) values (
    p_user_id, p_language_code, 'practice', 'active',
    jsonb_build_object(
      'origin', 'video_learning',
      'session_policy_version', p_policy_version,
      'video_id', p_video_id,
      'library_item_id', p_library_item_id,
      'support_language_code', p_support_language_code,
      'materialization', 'lazy',
      'max_activities', 3
    ), now()
  ) returning * into v_session;

  insert into v3.session_activities (
    session_id, concept_id, learning_object_id, activity_type, position,
    review_origin, prompt_payload, expected_response_payload, status
  )
  select v_session.id, (item->>'concept_id')::uuid,
         (item->>'learning_object_id')::uuid,
         (item->>'activity_type')::v3.activity_type,
         (item->>'position')::integer, false, '{}'::jsonb, null, 'planned'
  from jsonb_array_elements(p_selected) item;

  return jsonb_build_object('created', true, 'session', to_jsonb(v_session));
exception
  when unique_violation then
    select * into v_session from v3.learning_sessions
    where user_id = p_user_id and type = 'practice'
      and status in ('planned', 'active')
      and goal->>'origin' = 'video_learning'
      and goal->>'video_id' = p_video_id::text
    order by created_at limit 1;
    if v_session.id is not null
        and v_session.goal->>'support_language_code' = p_support_language_code then
      return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
    end if;
    raise;
end;
$$;

revoke all on function v3.start_or_resume_video_learning_session(
  uuid, uuid, uuid, text, text, text, jsonb
) from public, anon, authenticated;
grant execute on function v3.start_or_resume_video_learning_session(
  uuid, uuid, uuid, text, text, text, jsonb
) to service_role;

-- First validated video-learning evidence creates exactly one NEW state and
-- applies the normal Python FSRSAdapter transition in the same transaction.
-- The existing assessment application RPC still owns mastery/skill/CAS/event
-- writes. No ReviewState is created merely by viewing content or starting a
-- session, and review-origin provenance is never fabricated.
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
      and ls.type = 'practice' and ls.goal->>'origin' = 'video_learning'
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
