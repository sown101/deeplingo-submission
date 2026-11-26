-- 6B-2C: forward-only Content execution ownership. NOT authorized for hosted apply.
-- Deployment MUST quiesce old Content workers/producers/Beat and require zero running intents.
-- Old RPCs fail closed after cutover; do not roll back to an unfenced worker.
do $$ begin
  if exists (select 1 from v3.video_work_intents where state = 'running') then
    raise exception '6B-2C requires a drained running-intent cutover' using errcode = '23514';
  end if;
end $$;

alter table v3.video_work_intents
  add column claim_token uuid,
  add column claim_epoch bigint not null default 0,
  add column claimed_at timestamptz,
  add column lease_expires_at timestamptz,
  add column recovery_count bigint not null default 0,
  add constraint video_work_claim_epoch_chk check (claim_epoch >= 0),
  add constraint video_work_recovery_count_chk check (recovery_count >= 0),
  add constraint video_work_running_claim_chk check (
    state <> 'running' or (claim_token is not null and claim_epoch > 0
      and claimed_at is not null and lease_expires_at is not null and lease_expires_at > claimed_at));
create index video_work_expired_lease_idx on v3.video_work_intents (lease_expires_at, id)
  where state = 'running';

-- Consistent order: Video -> intent -> content. Recheck time AFTER waiting for locks.
-- DL001 is a recognizable stale-ownership error, NOT a retryable serialization failure.
create function v3.lock_current_content_claim(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_stage text
) returns v3.video_work_intents language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; vid uuid;
begin
  select video_id into vid from v3.video_work_intents where id = p_intent_id;
  perform 1 from v3.videos where id = vid for update;
  select * into i from v3.video_work_intents where id = p_intent_id for update;
  if not found or i.state <> 'running' or i.stage is distinct from p_stage
     or i.claim_token is distinct from p_claim_token or p_claim_token is null
     or i.claim_epoch is distinct from p_claim_epoch
     or i.lease_expires_at is null or i.lease_expires_at <= clock_timestamp() then
    raise exception 'Content execution ownership lost' using errcode = 'DL001';
  end if;
  return i;
end $$;

create function v3.claim_leased_content_work(
  p_intent_id uuid, p_preparation_version text default null, p_lease_seconds integer default 2100
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; v v3.videos%rowtype; ts timestamptz;
begin
  if p_lease_seconds is null or p_lease_seconds < 1 or p_lease_seconds > 86400 then
    raise exception 'Invalid Content lease' using errcode = '22023';
  end if;
  select * into i from v3.video_work_intents where id = p_intent_id;
  if not found then return null; end if;
  select * into v from v3.videos where id = i.video_id for update;
  if not found then return null; end if;
  select * into i from v3.video_work_intents where id = p_intent_id for update;
  ts := clock_timestamp();
  if i.state not in ('pending', 'dispatched')
     or (i.state = 'pending' and i.next_dispatch_at > ts) then return null; end if;
  if i.stage = 'transcript' then
    if v.processing_status not in ('pending', 'processing') then return null; end if;
    update v3.videos set processing_status = 'processing', processing_error = null,
      processing_error_code = null, processing_retryable = false,
      processing_started_at = ts, processing_completed_at = null, updated_at = ts where id = v.id;
  else
    if p_preparation_version is null or btrim(p_preparation_version) = ''
       or v.learning_status not in ('not_started', 'processing')
       or v.processing_status not in ('transcript_ready', 'learning_objects_ready') then return null; end if;
    update v3.videos set learning_status = 'processing', learning_preparation_version = p_preparation_version,
      learning_failure_code = null, learning_retryable = false,
      learning_started_at = ts, learning_completed_at = null, updated_at = ts where id = v.id;
  end if;
  update v3.video_work_intents set state = 'running', claim_token = extensions.gen_random_uuid(),
    claim_epoch = claim_epoch + 1, claimed_at = ts,
    lease_expires_at = ts + make_interval(secs => p_lease_seconds), updated_at = ts
    where id = i.id returning * into i;
  return to_jsonb(i);
end $$;

-- Bounded non-blocking discovery; retain UUID/generation and product processing.
-- Acquire Video first, never intent-first SKIP LOCKED (admission uses Video-first).
create function v3.recover_expired_content_work(p_limit integer default 50)
returns integer language plpgsql security invoker set search_path = '' as $$
declare candidate record; i v3.video_work_intents%rowtype; recovered integer := 0; ts timestamptz;
begin
  if p_limit is null or p_limit < 1 or p_limit > 100 then
    raise exception 'Recovery limit must be 1..100' using errcode = '22023';
  end if;
  for candidate in select id, video_id from v3.video_work_intents
    where state = 'running' and lease_expires_at <= clock_timestamp()
    order by lease_expires_at, id limit p_limit
  loop
    perform 1 from v3.videos where id = candidate.video_id for update skip locked;
    if not found then continue; end if;
    select * into i from v3.video_work_intents where id = candidate.id for update;
    ts := clock_timestamp();
    if i.state <> 'running' or i.lease_expires_at > ts then continue; end if;
    update v3.video_work_intents set state = 'pending', claim_token = null,
      lease_expires_at = null, recovery_count = recovery_count + 1,
      next_dispatch_at = ts, updated_at = ts where id = i.id;
    recovered := recovered + 1;
  end loop;
  return recovered;
end $$;

create function v3.write_claimed_transcript_track(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_track jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; t v3.video_transcripts%rowtype;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'transcript');
  t := jsonb_populate_record(null::v3.video_transcripts, p_track);
  if t.video_id is distinct from i.video_id or t.is_original is distinct from true
     or not exists (select 1 from v3.videos where id = i.video_id and original_language_code = t.language_code) then
    raise exception 'Invalid claimed transcript context' using errcode = '23514';
  end if;
  insert into v3.video_transcripts (video_id, language_code, source, is_original, provider_metadata)
    values (i.video_id, t.language_code, t.source, true, coalesce(t.provider_metadata, '{}'::jsonb))
    on conflict (video_id, language_code, source) do update
      set is_original = true, provider_metadata = excluded.provider_metadata, updated_at = clock_timestamp()
    returning * into t;
  return to_jsonb(t);
end $$;

create function v3.write_claimed_transcript_segments(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_segments jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; s v3.transcript_segments%rowtype; result jsonb := '[]'::jsonb;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'transcript');
  if jsonb_typeof(p_segments) <> 'array' then raise exception 'Invalid segment batch' using errcode = '22023'; end if;
  for s in select * from jsonb_populate_recordset(null::v3.transcript_segments, p_segments) loop
    if not exists (select 1 from v3.video_transcripts where id = s.transcript_id and video_id = i.video_id) then
      raise exception 'Segment outside claimed Video' using errcode = '23514';
    end if;
    insert into v3.transcript_segments (transcript_id, sequence_number, start_ms, end_ms, text)
      values (s.transcript_id, s.sequence_number, s.start_ms, s.end_ms, s.text)
      on conflict (transcript_id, sequence_number) do update set start_ms = excluded.start_ms,
        end_ms = excluded.end_ms, text = excluded.text, updated_at = clock_timestamp()
      returning * into s;
    result := result || jsonb_build_array(to_jsonb(s));
  end loop;
  return result;
end $$;

create function v3.write_claimed_segment_romanizations(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_romanizations jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; r v3.segment_romanizations%rowtype; result jsonb := '[]'::jsonb;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'transcript');
  if jsonb_typeof(p_romanizations) <> 'array' then raise exception 'Invalid romanization batch' using errcode = '22023'; end if;
  for r in select * from jsonb_populate_recordset(null::v3.segment_romanizations, p_romanizations) loop
    if not exists (select 1 from v3.transcript_segments s join v3.video_transcripts t on t.id = s.transcript_id
                   where s.id = r.transcript_segment_id and t.video_id = i.video_id) then
      raise exception 'Romanization outside claimed Video' using errcode = '23514';
    end if;
    insert into v3.segment_romanizations (transcript_segment_id, romanization_system_id, text, source)
      values (r.transcript_segment_id, r.romanization_system_id, r.text, r.source)
      on conflict (transcript_segment_id, romanization_system_id) do update
        set text = excluded.text, source = excluded.source, updated_at = clock_timestamp() returning * into r;
    result := result || jsonb_build_array(to_jsonb(r));
  end loop;
  return result;
end $$;

create function v3.resolve_claimed_concept(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_concept jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; c v3.concepts%rowtype;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'learning_preparation');
  c := jsonb_populate_record(null::v3.concepts, p_concept);
  if not exists (select 1 from v3.videos where id = i.video_id and original_language_code = c.language_code) then
    raise exception 'Concept language outside claim' using errcode = '23514';
  end if;
  -- Shared semantic identity is immutable here: never overwrite another Video's Concept.
  insert into v3.concepts (language_code, type, canonical_text, normalized_text, sense_key, metadata)
    values (c.language_code, c.type, c.canonical_text, c.normalized_text, c.sense_key, coalesce(c.metadata, '{}'::jsonb))
    on conflict (language_code, type, normalized_text, sense_key) do nothing;
  select ct.* into c from v3.concepts ct where ct.language_code = c.language_code and ct.type = c.type
    and ct.normalized_text = c.normalized_text and ct.sense_key = c.sense_key;
  return to_jsonb(c);
end $$;

create function v3.resolve_claimed_occurrence(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_occurrence jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; proposed v3.learning_objects%rowtype;
        existing v3.learning_objects%rowtype; ordinal integer;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'learning_preparation');
  proposed := jsonb_populate_record(null::v3.learning_objects, p_occurrence);
  if proposed.video_id is distinct from i.video_id or proposed.start_codepoint is null or proposed.end_codepoint is null
     or not exists (select 1 from v3.transcript_segments s join v3.video_transcripts t on t.id = s.transcript_id
       where s.id = proposed.transcript_segment_id and t.video_id = i.video_id) then
    raise exception 'Occurrence outside claimed Video' using errcode = '23514';
  end if;
  -- Serialize allocation on the source segment as well as this execution claim.
  perform 1 from v3.transcript_segments where id = proposed.transcript_segment_id for update;
  select * into existing from v3.learning_objects
    where concept_id = proposed.concept_id and transcript_segment_id = proposed.transcript_segment_id
      and start_codepoint = proposed.start_codepoint and end_codepoint = proposed.end_codepoint;
  if found then return to_jsonb(existing); end if;
  select coalesce(max(occurrence_index), 0) + 1 into ordinal from v3.learning_objects
    where concept_id = proposed.concept_id and transcript_segment_id = proposed.transcript_segment_id;
  insert into v3.learning_objects (concept_id, video_id, transcript_segment_id, occurrence_index,
    evidence_text, start_codepoint, end_codepoint, previous_context, next_context,
    start_ms, end_ms, ai_confidence, extraction_status, source, raw_ai_diagnostics)
  values (proposed.concept_id, i.video_id, proposed.transcript_segment_id, ordinal,
    proposed.evidence_text, proposed.start_codepoint, proposed.end_codepoint, proposed.previous_context, proposed.next_context,
    proposed.start_ms, proposed.end_ms, proposed.ai_confidence, proposed.extraction_status, proposed.source, proposed.raw_ai_diagnostics)
  returning * into existing;
  return to_jsonb(existing);
end $$;

create function v3.enrich_claimed_occurrence(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_learning_object_id uuid, p_enrichment jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; lo v3.learning_objects%rowtype; diag jsonb; langs jsonb; lang text;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'learning_preparation');
  select * into lo from v3.learning_objects where id = p_learning_object_id and video_id = i.video_id for update;
  if not found then raise exception 'Occurrence outside claimed Video' using errcode = '23514'; end if;
  lang := p_enrichment->>'target_language_code';
  if lang is null or btrim(lang) = '' or p_enrichment->>'concept_id' is distinct from lo.concept_id::text
     or not exists (select 1 from v3.concepts where id = lo.concept_id and sense_key = p_enrichment->>'concept_sense_key') then
    raise exception 'Invalid claimed enrichment context' using errcode = '23514';
  end if;
  -- Merge from LOCKED current JSONB, not the earlier read-modify-write snapshot.
  diag := coalesce(lo.raw_ai_diagnostics, '{}'::jsonb);
  langs := coalesce(diag->'enrichments', '{}'::jsonb);
  if diag->'enrichment'->>'target_language_code' is not null then
    langs := jsonb_build_object(diag->'enrichment'->>'target_language_code', diag->'enrichment') || langs;
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

create function v3.complete_claimed_transcript(p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; v v3.videos%rowtype; prep uuid; gen integer; ts timestamptz;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'transcript');
  ts := clock_timestamp();
  update v3.videos set processing_status = 'transcript_ready', processing_error = null,
    processing_error_code = null, processing_retryable = false, processing_completed_at = ts, updated_at = ts
    where id = i.video_id returning * into v;
  update v3.video_work_intents set state = 'completed', completed_at = ts, updated_at = ts where id = i.id;
  if v.learning_status = 'not_started' then
    select id into prep from v3.video_work_intents where video_id = v.id and stage = 'learning_preparation'
      and state in ('pending', 'dispatched', 'running') order by generation desc limit 1;
    if prep is null then
      select coalesce(max(generation), 0) + 1 into gen from v3.video_work_intents where video_id = v.id and stage = 'learning_preparation';
      insert into v3.video_work_intents (video_id, stage, generation) values (v.id, 'learning_preparation', gen) returning id into prep;
    end if;
  end if;
  return jsonb_build_object('video', to_jsonb(v), 'preparation_intent_id', prep);
end $$;

create function v3.complete_claimed_preparation(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_status text,
  p_usable_count integer, p_support_language_code text, p_failure_code text
) returns boolean language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; ts timestamptz;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'learning_preparation');
  if p_status is null or p_status not in ('ready', 'no_content') or p_usable_count is null or p_usable_count < 0
     or (p_status = 'ready' and (p_usable_count < 1 or p_support_language_code is null or btrim(p_support_language_code) = ''))
     or (p_status = 'no_content' and p_usable_count <> 0) then
    raise exception 'Invalid preparation completion' using errcode = '23514';
  end if;
  ts := clock_timestamp();
  update v3.videos set learning_status = p_status, learning_object_count = p_usable_count,
    learning_prepared_language_code = p_support_language_code, learning_failure_code = p_failure_code,
    learning_retryable = false, learning_completed_at = ts, updated_at = ts where id = i.video_id;
  update v3.video_work_intents set state = 'completed', completed_at = ts, updated_at = ts where id = i.id;
  return true;
end $$;

create function v3.fail_claimed_content_work(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_failure_code text,
  p_retryable boolean, p_retry_delay integer default null
) returns text language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; stage_name text; ts timestamptz;
begin
  select stage into stage_name from v3.video_work_intents where id = p_intent_id;
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, stage_name);
  if p_failure_code is null or length(p_failure_code) > 64 or p_failure_code !~ '^[a-z_]+$'
     or p_retryable is null or (p_retry_delay is not null and (not p_retryable or p_retry_delay < 0 or p_retry_delay > 3600)) then
    raise exception 'Invalid safe Content failure' using errcode = '22023';
  end if;
  ts := clock_timestamp();
  if i.stage = 'transcript' then
    update v3.videos set processing_status = case when p_retry_delay is null then 'failed'::v3.processing_status else 'pending'::v3.processing_status end,
      processing_error = null, processing_error_code = case when p_retry_delay is null then p_failure_code else null end,
      processing_retryable = p_retry_delay is null and p_retryable,
      processing_completed_at = case when p_retry_delay is null then ts else null end, updated_at = ts where id = i.video_id;
  else
    update v3.videos set learning_status = case when p_retry_delay is null then 'failed' else 'not_started' end,
      learning_failure_code = case when p_retry_delay is null then p_failure_code else null end,
      learning_retryable = p_retry_delay is null and p_retryable,
      learning_completed_at = case when p_retry_delay is null then ts else null end, updated_at = ts where id = i.video_id;
  end if;
  update v3.video_work_intents set state = case when p_retry_delay is null then 'failed' else 'pending' end,
    claim_token = case when p_retry_delay is null then claim_token else null end,
    lease_expires_at = case when p_retry_delay is null then lease_expires_at else null end,
    completed_at = case when p_retry_delay is null then ts else null end,
    next_dispatch_at = ts + make_interval(secs => coalesce(p_retry_delay, 0)), updated_at = ts where id = i.id;
  return case when p_retry_delay is null then 'failed' else 'pending' end;
end $$;

-- Retire unkeyed execution RPCs. Keep signatures only as explicit fail-closed cutover traps.
create or replace function v3.claim_video_content_work(p_intent_id uuid, p_preparation_version text default null)
returns jsonb language plpgsql security invoker set search_path = '' as $$
begin raise exception 'Leased Content worker required' using errcode = 'DL001'; end $$;
create or replace function v3.complete_transcript_content_work(p_intent_id uuid)
returns jsonb language plpgsql security invoker set search_path = '' as $$
begin raise exception 'Fenced Content completion required' using errcode = 'DL001'; end $$;
create or replace function v3.reset_failed_video_content_work(p_intent_id uuid, p_delay_seconds integer)
returns boolean language plpgsql security invoker set search_path = '' as $$
begin raise exception 'Fenced Content failure required' using errcode = 'DL001'; end $$;
revoke all on function v3.claim_video_content_work(uuid, text) from public, anon, authenticated, service_role;
revoke all on function v3.complete_transcript_content_work(uuid) from public, anon, authenticated, service_role;
revoke all on function v3.reset_failed_video_content_work(uuid, integer) from public, anon, authenticated, service_role;

create function v3.link_claimed_concept_reference(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint,
  p_concept_id uuid, p_dictionary_entry_id uuid, p_relation_type text
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; link v3.concept_dictionary_links%rowtype;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'learning_preparation');
  if not exists (select 1 from v3.concepts c join v3.videos v on v.original_language_code = c.language_code
                 where c.id = p_concept_id and v.id = i.video_id) then
    raise exception 'Reference language outside claim' using errcode = '23514';
  end if;
  insert into v3.concept_dictionary_links (concept_id, dictionary_entry_id, relation_type)
    values (p_concept_id, p_dictionary_entry_id, p_relation_type)
    on conflict (concept_id, dictionary_entry_id) do nothing;
  select * into link from v3.concept_dictionary_links
    where concept_id = p_concept_id and dictionary_entry_id = p_dictionary_entry_id;
  return to_jsonb(link);
end $$;
revoke all on function v3.link_claimed_concept_reference(uuid, uuid, bigint, uuid, uuid, text) from public, anon, authenticated;
grant execute on function v3.link_claimed_concept_reference(uuid, uuid, bigint, uuid, uuid, text) to service_role;

-- Explicit per-function privileges; no broad GRANT ALL FUNCTIONS.
revoke all on function v3.lock_current_content_claim(uuid, uuid, bigint, text) from public, anon, authenticated;
grant execute on function v3.lock_current_content_claim(uuid, uuid, bigint, text) to service_role;
revoke all on function v3.claim_leased_content_work(uuid, text, integer) from public, anon, authenticated;
grant execute on function v3.claim_leased_content_work(uuid, text, integer) to service_role;
revoke all on function v3.recover_expired_content_work(integer) from public, anon, authenticated;
grant execute on function v3.recover_expired_content_work(integer) to service_role;
revoke all on function v3.write_claimed_transcript_track(uuid, uuid, bigint, jsonb) from public, anon, authenticated;
grant execute on function v3.write_claimed_transcript_track(uuid, uuid, bigint, jsonb) to service_role;
revoke all on function v3.write_claimed_transcript_segments(uuid, uuid, bigint, jsonb) from public, anon, authenticated;
grant execute on function v3.write_claimed_transcript_segments(uuid, uuid, bigint, jsonb) to service_role;
revoke all on function v3.write_claimed_segment_romanizations(uuid, uuid, bigint, jsonb) from public, anon, authenticated;
grant execute on function v3.write_claimed_segment_romanizations(uuid, uuid, bigint, jsonb) to service_role;
revoke all on function v3.resolve_claimed_concept(uuid, uuid, bigint, jsonb) from public, anon, authenticated;
grant execute on function v3.resolve_claimed_concept(uuid, uuid, bigint, jsonb) to service_role;
revoke all on function v3.resolve_claimed_occurrence(uuid, uuid, bigint, jsonb) from public, anon, authenticated;
grant execute on function v3.resolve_claimed_occurrence(uuid, uuid, bigint, jsonb) to service_role;
revoke all on function v3.enrich_claimed_occurrence(uuid, uuid, bigint, uuid, jsonb) from public, anon, authenticated;
grant execute on function v3.enrich_claimed_occurrence(uuid, uuid, bigint, uuid, jsonb) to service_role;
revoke all on function v3.complete_claimed_transcript(uuid, uuid, bigint) from public, anon, authenticated;
grant execute on function v3.complete_claimed_transcript(uuid, uuid, bigint) to service_role;
revoke all on function v3.complete_claimed_preparation(uuid, uuid, bigint, text, integer, text, text) from public, anon, authenticated;
grant execute on function v3.complete_claimed_preparation(uuid, uuid, bigint, text, integer, text, text) to service_role;
revoke all on function v3.fail_claimed_content_work(uuid, uuid, bigint, text, boolean, integer) from public, anon, authenticated;
grant execute on function v3.fail_claimed_content_work(uuid, uuid, bigint, text, boolean, integer) to service_role;
