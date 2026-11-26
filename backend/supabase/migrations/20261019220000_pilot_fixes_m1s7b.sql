-- M1 S7b: fixes found by the M1 review before the pilot. Forward-only; earlier migrations are not
-- rewritten.
--
-- 1. Region admission joins the shared Content admission order (ADR-012): the global admission
--    lock before any Video lock, and no new region intent while 50 Content intents are active
--    (`busy`, not charged to the learner's region budget).
-- 2. A claimed enrichment keeps the first meaning stored for its language and prompt version, so
--    overlapping regions (or the Video and a region) cannot overwrite each other; a newer prompt
--    version replaces an older one.
-- 3. Quick review may ground a question on a real occurrence in one of the learner's own Library
--    videos (`learning_object_id`) instead of an ExampleSentence; every payload check fails closed.
-- 4. Practice-log and companion-memory rows are unreadable after they expire, and a bounded purge
--    (run by Beat) deletes them for every learner, not only on the learner's next write.

-- 1. Region admission ---------------------------------------------------------------------------
create or replace function v3.admit_region_preparation(
  p_user_id uuid, p_library_item_id uuid, p_transcript_id uuid,
  p_start_segment_id uuid, p_end_segment_id uuid,
  p_support_language_code text, p_preparation_version text,
  p_max_segments integer, p_limit integer, p_window_seconds integer
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare lv v3.learner_videos%rowtype; v v3.videos%rowtype; t v3.video_transcripts%rowtype;
        s1 v3.transcript_segments%rowtype; s2 v3.transcript_segments%rowtype;
        r v3.video_region_preparations%rowtype; used integer; oldest timestamptz;
        intent uuid; gen integer;
begin
  if p_max_segments is null or p_max_segments < 1 or p_max_segments > 100
     or p_limit is null or p_limit < 1 or p_limit > 1000
     or p_window_seconds is null or p_window_seconds < 60 or p_window_seconds > 2678400
     or p_support_language_code is null or btrim(p_support_language_code) = ''
     or p_preparation_version is null or btrim(p_preparation_version) = '' then
    raise exception 'Invalid region preparation policy' using errcode = '22023';
  end if;
  select * into lv from v3.learner_videos where id = p_library_item_id and user_id = p_user_id;
  if not found then return jsonb_build_object('status', 'not_found'); end if;
  -- Same order as admit_video_content_work: the admission lock, then the Video.
  perform pg_advisory_xact_lock(6202050::bigint);
  select * into v from v3.videos where id = lv.video_id for update;
  select * into t from v3.video_transcripts
    where id = p_transcript_id and video_id = v.id and is_original and language_code = v.original_language_code;
  if not found then return jsonb_build_object('status', 'region_unavailable'); end if;
  select * into s1 from v3.transcript_segments where id = p_start_segment_id and transcript_id = t.id;
  select * into s2 from v3.transcript_segments where id = p_end_segment_id and transcript_id = t.id;
  if s1.id is null or s2.id is null or s2.sequence_number < s1.sequence_number
     or s2.sequence_number - s1.sequence_number + 1 > p_max_segments then
    return jsonb_build_object('status', 'region_unavailable');
  end if;
  if v.processing_status not in ('transcript_ready', 'learning_objects_ready') then
    return jsonb_build_object('status', 'transcript_unavailable');
  end if;

  perform pg_advisory_xact_lock(hashtextextended('region_preparation:' || p_user_id::text, 0));
  select * into r from v3.video_region_preparations
    where transcript_id = t.id and start_segment_id = s1.id and end_segment_id = s2.id
      and support_language_code = p_support_language_code and preparation_version = p_preparation_version
    for update;

  if found and not (r.status = 'failed' and r.retryable) then
    return jsonb_build_object('status', r.status, 'region_preparation_id', r.id, 'intent_id', null,
                              'dispatch_now', false, 'usable_count', r.usable_count, 'retryable', r.retryable);
  end if;
  -- Safety cap shared with Video admission: one reconciler batch, not a measured capacity.
  if (select count(*) from v3.video_work_intents where state in ('pending', 'dispatched', 'running')) >= 50 then
    return jsonb_build_object('status', 'busy', 'region_preparation_id', r.id, 'retryable', true);
  end if;

  if found then
    select coalesce(max(generation), 0) + 1 into gen from v3.video_work_intents
      where region_preparation_id = r.id and stage = 'region_preparation';
    update v3.video_region_preparations set status = 'pending', failure_code = null, retryable = false,
      completed_at = null, updated_at = now() where id = r.id returning * into r;
    insert into v3.video_work_intents (video_id, stage, generation, region_preparation_id)
      values (v.id, 'region_preparation', gen, r.id) returning id into intent;
    return jsonb_build_object('status', r.status, 'region_preparation_id', r.id, 'intent_id', intent,
                              'dispatch_now', true, 'usable_count', r.usable_count, 'retryable', false);
  end if;

  select count(*), min(requested_at) into used, oldest from v3.learner_region_preparation_requests
    where user_id = p_user_id and requested_at > now() - make_interval(secs => p_window_seconds);
  if used >= p_limit then
    return jsonb_build_object('status', 'budget_exhausted',
                              'reset_at', oldest + make_interval(secs => p_window_seconds));
  end if;
  insert into v3.video_region_preparations (video_id, transcript_id, start_segment_id, end_segment_id,
      start_sequence, end_sequence, support_language_code, preparation_version)
    values (v.id, t.id, s1.id, s2.id, s1.sequence_number, s2.sequence_number,
            p_support_language_code, p_preparation_version)
    returning * into r;
  insert into v3.learner_region_preparation_requests (user_id, region_preparation_id) values (p_user_id, r.id);
  insert into v3.video_work_intents (video_id, stage, generation, region_preparation_id)
    values (v.id, 'region_preparation', 1, r.id) returning id into intent;
  return jsonb_build_object('status', r.status, 'region_preparation_id', r.id, 'intent_id', intent,
                            'dispatch_now', true, 'usable_count', 0, 'retryable', false);
end $$;

-- 2. Claimed enrichment: first meaning per language and prompt version wins --------------------
create or replace function v3.enrich_claimed_occurrence(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_learning_object_id uuid, p_enrichment jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; lo v3.learning_objects%rowtype; diag jsonb; langs jsonb; lang text;
begin
  i := v3.lock_current_preparation_claim(p_intent_id, p_claim_token, p_claim_epoch);
  select * into lo from v3.learning_objects where id = p_learning_object_id and video_id = i.video_id for update;
  if not found then raise exception 'Occurrence outside claimed Video' using errcode = '23514'; end if;
  if not v3.preparation_claim_covers_segment(i.stage, i.region_preparation_id, lo.transcript_segment_id) then
    raise exception 'Occurrence outside claimed region' using errcode = '23514';
  end if;
  lang := p_enrichment->>'target_language_code';
  if lang is null or btrim(lang) = '' or p_enrichment->>'concept_id' is distinct from lo.concept_id::text
     or coalesce(btrim(p_enrichment->>'prompt_version'), '') = ''
     or not exists (select 1 from v3.concepts where id = lo.concept_id and sense_key = p_enrichment->>'concept_sense_key') then
    raise exception 'Invalid claimed enrichment context' using errcode = '23514';
  end if;
  -- Merge from LOCKED current JSONB, not the earlier read-modify-write snapshot.
  diag := coalesce(lo.raw_ai_diagnostics, '{}'::jsonb);
  langs := coalesce(diag->'enrichments', '{}'::jsonb);
  if diag->'enrichment'->>'target_language_code' is not null then
    langs := jsonb_build_object(diag->'enrichment'->>'target_language_code', diag->'enrichment') || langs;
  end if;
  if langs->lang->>'concept_id' = lo.concept_id::text
     and langs->lang->>'concept_sense_key' = p_enrichment->>'concept_sense_key'
     and langs->lang->>'prompt_version' = p_enrichment->>'prompt_version' then
    return to_jsonb(lo);  -- another claim stored this meaning first; keep it
  end if;
  langs := langs || jsonb_build_object(lang, p_enrichment);
  update v3.learning_objects set
    difficulty_score = (p_enrichment->'difficulty'->>'score')::numeric,
    learning_value_score = (p_enrichment->'learning_value'->>'score')::numeric,
    ai_confidence = (p_enrichment->>'confidence')::numeric,
    raw_ai_diagnostics = diag || jsonb_build_object('enrichments', langs, 'enrichment', p_enrichment),
    updated_at = clock_timestamp() where id = lo.id returning * into lo;
  return to_jsonb(lo);
end $$;

-- 3. Quick review: a question grounded on an ExampleSentence or the learner's own video ----------
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
    -- Exactly one source, named the same way in the stored provenance. Any missing field fails.
    if coalesce(
        (v_example is null) = (v_object is null)
        or jsonb_typeof(v_item->'prompt_payload') <> 'object'
        or jsonb_typeof(v_item->'expected_response_payload') <> 'object'
        or v_item->'prompt_payload'->>'activity_kind' <> 'mcq'
        or jsonb_typeof(v_item->'prompt_payload'->'options') <> 'array'
        or jsonb_array_length(v_item->'prompt_payload'->'options') <> 4
        or jsonb_typeof(v_item->'expected_response_payload'->'correct_option') <> 'number'
        or (v_item->'expected_response_payload'->>'correct_option')::numeric not in (0, 1, 2)
        or v_item->'prompt_payload'->'options'->>3 <> 'Không nhớ'
        or v_prov->>'source_concept_id' <> v_concept::text
        or (v_prov->>'source_example_sentence_id') is distinct from v_example::text
        or (v_prov->>'source_learning_object_id') is distinct from v_object::text,
        true) then
      raise exception 'quick_review_conflict: invalid_payload';
    end if;
    if v_example is not null and not exists (
      select 1 from v3.example_sentences e join v3.concepts c on c.id = e.concept_id
      where e.id = v_example and e.concept_id = v_concept
        and c.language_code = p_language_code and e.language_code = p_language_code
    ) then
      raise exception 'quick_review_conflict: word_or_example';
    end if;
    -- A video sentence only from a video in this learner's own Library.
    if v_object is not null and not exists (
      select 1 from v3.learning_objects lo
        join v3.concepts c on c.id = lo.concept_id
        join v3.learner_videos lv on lv.video_id = lo.video_id and lv.user_id = p_user_id
      where lo.id = v_object and lo.concept_id = v_concept and c.language_code = p_language_code
    ) then
      raise exception 'quick_review_conflict: word_or_example';
    end if;

    if jsonb_typeof(v_item->'review_state_id') = 'string' then
      -- A review opportunity: the learner's own due state, at the version the question was built for.
      select * into v_state from v3.review_states
      where id = (v_item->>'review_state_id')::uuid and user_id = p_user_id and concept_id = v_concept
        and review_mode = 'concept_to_meaning';
      if v_state.id is null or v_state.version is distinct from (v_item->>'source_review_state_version')::integer
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
      v_session.id, (v_item->>'concept_id')::uuid,
      case when jsonb_typeof(v_item->'learning_object_id') = 'string' then (v_item->>'learning_object_id')::uuid end,
      case when jsonb_typeof(v_item->'example_sentence_id') = 'string' then (v_item->>'example_sentence_id')::uuid end,
      'mcq'::v3.activity_type, v_position,
      coalesce(jsonb_typeof(v_item->'review_state_id') = 'string', false),
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
end $fn$;

revoke all on function v3.start_or_resume_quick_review_session(uuid, text, text, text, jsonb)
  from public, anon, authenticated;
grant execute on function v3.start_or_resume_quick_review_session(uuid, text, text, text, jsonb) to service_role;

-- 4. Expiry: unreadable once expired, and purged for everyone -------------------------------------
drop policy if exists "Users can read own practice events" on v3.learner_practice_events;
create policy "Users can read own practice events"
  on v3.learner_practice_events for select
  to authenticated
  using ((select auth.uid()) = user_id and expires_at > now());

drop policy if exists "Users can read own companion memory" on v3.learner_companion_memory;
create policy "Users can read own companion memory"
  on v3.learner_companion_memory for select
  to authenticated
  using ((select auth.uid()) = user_id and expires_at > now());

create or replace function v3.purge_expired_learner_data(p_limit integer default 1000)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare practice integer; memory integer;
begin
  if p_limit is null or p_limit < 1 or p_limit > 10000 then
    raise exception 'Invalid purge limit' using errcode = '22023';
  end if;
  delete from v3.learner_practice_events where id in (
    select id from v3.learner_practice_events where expires_at <= now() limit p_limit);
  get diagnostics practice = row_count;
  delete from v3.learner_companion_memory where id in (
    select id from v3.learner_companion_memory where expires_at <= now() limit p_limit);
  get diagnostics memory = row_count;
  return jsonb_build_object('practice_events', practice, 'companion_memory', memory);
end $$;

revoke all on function v3.purge_expired_learner_data(integer) from public, anon, authenticated;
grant execute on function v3.purge_expired_learner_data(integer) to service_role;
