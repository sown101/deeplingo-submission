-- M1 S2: learning preparation per study region on the durable Content work intents.
--
-- Amends ADR-010/011/012 (see their "Region preparation stage" sections): a third stage,
-- `region_preparation`, keyed by one row of v3.video_region_preparations instead of by the
-- Video. The Video-level `transcript` and `learning_preparation` stages keep their behavior,
-- Video readiness and indexes; a region intent never changes v3.videos. Leases, epochs,
-- fencing tokens and retry budgets are reused unchanged (3 claims for a preparation stage).
-- Shared content written by a region claim goes through the same fenced RPCs, which now also
-- reject an occurrence outside the claimed region. Forward-only.

-- 1. Region identity and readiness (global content, not learner state).
create table if not exists v3.video_region_preparations (
  id uuid primary key default extensions.gen_random_uuid(),
  video_id uuid not null references v3.videos(id) on delete cascade,
  transcript_id uuid not null references v3.video_transcripts(id) on delete cascade,
  start_segment_id uuid not null references v3.transcript_segments(id) on delete cascade,
  end_segment_id uuid not null references v3.transcript_segments(id) on delete cascade,
  start_sequence integer not null,
  end_sequence integer not null,
  support_language_code text not null check (btrim(support_language_code) <> ''),
  preparation_version text not null check (btrim(preparation_version) <> ''),
  status text not null default 'pending'
    check (status in ('pending', 'processing', 'ready', 'no_content', 'failed')),
  usable_count integer not null default 0 check (usable_count >= 0),
  failure_code text,
  retryable boolean not null default false,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint video_region_preparations_range_chk check (end_sequence >= start_sequence),
  constraint video_region_preparations_key unique
    (transcript_id, start_segment_id, end_segment_id, support_language_code, preparation_version)
);

create index if not exists video_region_preparations_coverage_idx
  on v3.video_region_preparations (transcript_id, support_language_code, preparation_version, status);

comment on table v3.video_region_preparations is
  'M1 S2: learning preparation of one segment range of one transcript version, per support '
  'language and preparation version. Global content readiness; not learner state.';

alter table v3.video_region_preparations enable row level security;
revoke all privileges on v3.video_region_preparations from public, anon, authenticated;
grant all privileges on v3.video_region_preparations to service_role;

-- 2. Per-learner budget ledger (same pattern as O12): a learner is charged once per region
-- it first asks for; regions that already exist, retries and ready regions are free.
create table if not exists v3.learner_region_preparation_requests (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  region_preparation_id uuid not null references v3.video_region_preparations(id) on delete cascade,
  requested_at timestamptz not null default now(),
  primary key (user_id, region_preparation_id)
);

create index if not exists learner_region_preparation_requests_window_idx
  on v3.learner_region_preparation_requests (user_id, requested_at desc);

alter table v3.learner_region_preparation_requests enable row level security;
revoke all privileges on v3.learner_region_preparation_requests from public, anon, authenticated;
grant all privileges on v3.learner_region_preparation_requests to service_role;

-- 3. The intent stage. Video stages keep "one active intent and one generation sequence per
-- (Video, stage)"; the region stage has the same two guarantees per region.
alter table v3.video_work_intents
  add column if not exists region_preparation_id uuid
    references v3.video_region_preparations(id) on delete cascade;

alter table v3.video_work_intents drop constraint if exists video_work_intents_stage_check;
alter table v3.video_work_intents add constraint video_work_intents_stage_check
  check (stage in ('transcript', 'learning_preparation', 'region_preparation'));
alter table v3.video_work_intents drop constraint if exists video_work_intents_region_scope_chk;
alter table v3.video_work_intents add constraint video_work_intents_region_scope_chk
  check ((stage = 'region_preparation') = (region_preparation_id is not null));

alter table v3.video_work_intents drop constraint if exists video_work_intents_generation_unique;
create unique index if not exists video_work_intents_generation_unique
  on v3.video_work_intents (video_id, stage, generation) where stage <> 'region_preparation';
create unique index if not exists video_work_intents_region_generation_unique
  on v3.video_work_intents (region_preparation_id, generation) where stage = 'region_preparation';

drop index if exists v3.video_work_intents_one_active_stage_idx;
create unique index video_work_intents_one_active_stage_idx
  on v3.video_work_intents (video_id, stage)
  where state in ('pending', 'dispatched', 'running') and stage <> 'region_preparation';
create unique index if not exists video_work_intents_one_active_region_idx
  on v3.video_work_intents (region_preparation_id)
  where state in ('pending', 'dispatched', 'running') and stage = 'region_preparation';

-- 4. Fencing helpers.
create or replace function v3.lock_current_preparation_claim(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint
) returns v3.video_work_intents language plpgsql security invoker set search_path = '' as $$
declare stage_name text;
begin
  select stage into stage_name from v3.video_work_intents where id = p_intent_id;
  if stage_name is null or stage_name not in ('learning_preparation', 'region_preparation') then
    raise exception 'Content execution ownership lost' using errcode = 'DL001';
  end if;
  return v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, stage_name);
end $$;

create or replace function v3.preparation_claim_covers_segment(
  p_stage text, p_region_preparation_id uuid, p_segment_id uuid
) returns boolean language sql stable security invoker set search_path = '' as $$
  select p_stage <> 'region_preparation' or exists (
    select 1 from v3.video_region_preparations r
    join v3.transcript_segments s on s.transcript_id = r.transcript_id
    where r.id = p_region_preparation_id and s.id = p_segment_id
      and s.sequence_number between r.start_sequence and r.end_sequence
  )
$$;

-- 5. Claim, failure and recovery: the region branch changes only its region row.
create or replace function v3.claim_leased_content_work(
  p_intent_id uuid, p_preparation_version text default null, p_lease_seconds integer default 2100
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; v v3.videos%rowtype;
        r v3.video_region_preparations%rowtype; ts timestamptz;
begin
  if p_lease_seconds is null or p_lease_seconds < 1 or p_lease_seconds > 86400 then
    raise exception 'Invalid Content lease' using errcode = '22023';
  end if;
  select * into i from v3.video_work_intents where id = p_intent_id;
  if not found then return null; end if;
  select * into v from v3.videos where id = i.video_id for update;
  if not found then return null; end if;
  select * into i from v3.video_work_intents where id = p_intent_id for update;
  if i.stage = 'region_preparation' then
    select * into r from v3.video_region_preparations where id = i.region_preparation_id for update;
    if not found then return null; end if;
  end if;
  ts := clock_timestamp();
  if i.state not in ('pending', 'dispatched')
     or (i.state = 'pending' and i.next_dispatch_at > ts)
     or (i.next_retry_at is not null and i.next_retry_at > ts) then return null; end if;
  if i.claim_epoch >= (case when i.stage = 'transcript' then 4 else 3 end) then
    if i.stage = 'transcript' then
      update v3.videos set processing_status = 'failed', processing_error = null,
        processing_error_code = 'processing_failed', processing_retryable = true,
        processing_completed_at = ts, updated_at = ts where id = i.video_id;
    elsif i.stage = 'learning_preparation' then
      update v3.videos set learning_status = 'failed', learning_failure_code = 'preparation_failed',
        learning_retryable = true, learning_completed_at = ts, updated_at = ts where id = i.video_id;
    else
      update v3.video_region_preparations set status = 'failed', failure_code = 'preparation_failed',
        retryable = true, completed_at = ts, updated_at = ts where id = r.id;
    end if;
    update v3.video_work_intents set state = 'failed', completed_at = ts,
      claim_token = null, lease_expires_at = null, next_retry_at = null, updated_at = ts,
      failure_code = coalesce(failure_code, 'retry_exhausted'),
      failure_class = coalesce(failure_class, 'transient'), last_error_at = ts where id = i.id;
    return null;
  end if;
  if i.stage = 'transcript' then
    if v.processing_status not in ('pending', 'processing') then return null; end if;
    update v3.videos set processing_status = 'processing', processing_error = null,
      processing_error_code = null, processing_retryable = false,
      processing_started_at = ts, processing_completed_at = null, updated_at = ts where id = v.id;
  elsif i.stage = 'learning_preparation' then
    if p_preparation_version is null or btrim(p_preparation_version) = ''
       or v.learning_status not in ('not_started', 'processing')
       or v.processing_status not in ('transcript_ready', 'learning_objects_ready') then return null; end if;
    update v3.videos set learning_status = 'processing', learning_preparation_version = p_preparation_version,
      learning_failure_code = null, learning_retryable = false,
      learning_started_at = ts, learning_completed_at = null, updated_at = ts where id = v.id;
  else
    if r.status not in ('pending', 'processing')
       or v.processing_status not in ('transcript_ready', 'learning_objects_ready') then return null; end if;
    if p_preparation_version is distinct from r.preparation_version then
      -- A worker of another version must not prepare this region; a request under the new
      -- version is a different region row. Terminal, so the intent is not redispatched forever.
      update v3.video_region_preparations set status = 'failed', failure_code = 'preparation_version_changed',
        retryable = false, completed_at = ts, updated_at = ts where id = r.id;
      update v3.video_work_intents set state = 'failed', completed_at = ts, claim_token = null,
        lease_expires_at = null, next_retry_at = null, updated_at = ts, failure_class = 'permanent',
        failure_code = 'configuration_error', last_error_at = ts where id = i.id;
      return null;
    end if;
    update v3.video_region_preparations set status = 'processing', failure_code = null, retryable = false,
      started_at = ts, completed_at = null, updated_at = ts where id = r.id;
  end if;
  update v3.video_work_intents set state = 'running', claim_token = extensions.gen_random_uuid(),
    claim_epoch = claim_epoch + 1, claimed_at = ts, next_retry_at = null,
    lease_expires_at = ts + make_interval(secs => p_lease_seconds), updated_at = ts
    where id = i.id returning * into i;
  return to_jsonb(i);
end $$;

create or replace function v3.record_content_work_failure(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint,
  p_failure_class text, p_failure_code text, p_explicit_retry boolean
) returns text language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; stage_name text; ts timestamptz; delay_seconds integer;
begin
  select stage into stage_name from v3.video_work_intents where id = p_intent_id;
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, stage_name);
  if p_failure_class is null or p_failure_class not in ('transient', 'permanent', 'unknown')
     or p_failure_code is null or p_failure_code not in (
       'transient_timeout', 'transient_network', 'provider_rate_limit', 'provider_temporary',
       'database_temporary', 'content_unavailable', 'validation_failed', 'invariant_violation',
       'configuration_error', 'unknown_failure')
     or p_explicit_retry is null or (p_failure_class = 'permanent' and p_explicit_retry) then
    raise exception 'Invalid safe Content failure' using errcode = '22023';
  end if;
  ts := clock_timestamp();
  if p_failure_class = 'transient'
     and i.claim_epoch < (case when i.stage = 'transcript' then 4 else 3 end) then
    delay_seconds := (60 * power(2, i.claim_epoch - 1))::integer;
  end if;
  if i.stage = 'transcript' then
    update v3.videos set processing_status = case when delay_seconds is null then 'failed'::v3.processing_status else 'pending'::v3.processing_status end,
      processing_error = null, processing_error_code = case when delay_seconds is null then 'processing_failed' else null end,
      processing_retryable = delay_seconds is null and p_explicit_retry,
      processing_completed_at = case when delay_seconds is null then ts else null end, updated_at = ts where id = i.video_id;
  elsif i.stage = 'learning_preparation' then
    update v3.videos set learning_status = case when delay_seconds is null then 'failed' else 'not_started' end,
      learning_failure_code = case when delay_seconds is null then 'preparation_failed' else null end,
      learning_retryable = delay_seconds is null and p_explicit_retry,
      learning_completed_at = case when delay_seconds is null then ts else null end, updated_at = ts where id = i.video_id;
  else
    update v3.video_region_preparations set status = case when delay_seconds is null then 'failed' else 'pending' end,
      failure_code = case when delay_seconds is null then 'preparation_failed' else null end,
      retryable = delay_seconds is null and p_explicit_retry,
      completed_at = case when delay_seconds is null then ts else null end, updated_at = ts
      where id = i.region_preparation_id;
  end if;
  update v3.video_work_intents set state = case when delay_seconds is null then 'failed' else 'pending' end,
    claim_token = null, lease_expires_at = null,
    completed_at = case when delay_seconds is null then ts else null end,
    failure_class = p_failure_class, failure_code = p_failure_code, last_error_at = ts,
    next_dispatch_at = ts + make_interval(secs => coalesce(delay_seconds, 0)),
    next_retry_at = case when delay_seconds is null then null else ts + make_interval(secs => delay_seconds) end,
    updated_at = ts where id = i.id;
  return case when delay_seconds is null then 'failed' else 'pending' end;
end $$;

create or replace function v3.recover_expired_content_work(p_limit integer default 50)
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
    if i.claim_epoch >= (case when i.stage = 'transcript' then 4 else 3 end) then
      if i.stage = 'transcript' then
        update v3.videos set processing_status = 'failed', processing_error = null,
          processing_error_code = 'processing_failed', processing_retryable = true,
          processing_completed_at = ts, updated_at = ts where id = i.video_id;
      elsif i.stage = 'learning_preparation' then
        update v3.videos set learning_status = 'failed', learning_failure_code = 'preparation_failed',
          learning_retryable = true, learning_completed_at = ts, updated_at = ts where id = i.video_id;
      else
        update v3.video_region_preparations set status = 'failed', failure_code = 'preparation_failed',
          retryable = true, completed_at = ts, updated_at = ts where id = i.region_preparation_id;
      end if;
      update v3.video_work_intents set state = 'failed', claim_token = null,
        lease_expires_at = null, recovery_count = recovery_count + 1, completed_at = ts, next_retry_at = null,
        failure_class = 'transient', failure_code = 'lease_lost', last_error_at = ts,
        updated_at = ts where id = i.id;
    else
      update v3.video_work_intents set state = 'pending', claim_token = null,
        lease_expires_at = null, recovery_count = recovery_count + 1,
        failure_class = 'transient', failure_code = 'lease_lost', last_error_at = ts,
        next_dispatch_at = ts + make_interval(secs => (60 * power(2, i.claim_epoch - 1))::integer),
        next_retry_at = ts + make_interval(secs => (60 * power(2, i.claim_epoch - 1))::integer),
        updated_at = ts where id = i.id;
    end if;
    recovered := recovered + 1;
  end loop;
  return recovered;
end $$;

-- 6. Fenced shared-content writes accept both preparation stages; a region claim may write
-- occurrences and enrichment only inside its own segment range.
create or replace function v3.resolve_claimed_concept(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_concept jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; c v3.concepts%rowtype;
begin
  i := v3.lock_current_preparation_claim(p_intent_id, p_claim_token, p_claim_epoch);
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

create or replace function v3.resolve_claimed_occurrence(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_occurrence jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; proposed v3.learning_objects%rowtype;
        existing v3.learning_objects%rowtype; ordinal integer;
begin
  i := v3.lock_current_preparation_claim(p_intent_id, p_claim_token, p_claim_epoch);
  proposed := jsonb_populate_record(null::v3.learning_objects, p_occurrence);
  if proposed.video_id is distinct from i.video_id or proposed.start_codepoint is null or proposed.end_codepoint is null
     or not exists (select 1 from v3.transcript_segments s join v3.video_transcripts t on t.id = s.transcript_id
       where s.id = proposed.transcript_segment_id and t.video_id = i.video_id) then
    raise exception 'Occurrence outside claimed Video' using errcode = '23514';
  end if;
  if not v3.preparation_claim_covers_segment(i.stage, i.region_preparation_id, proposed.transcript_segment_id) then
    raise exception 'Occurrence outside claimed region' using errcode = '23514';
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

create or replace function v3.link_claimed_concept_reference(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint,
  p_concept_id uuid, p_dictionary_entry_id uuid, p_relation_type text
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; link v3.concept_dictionary_links%rowtype;
begin
  i := v3.lock_current_preparation_claim(p_intent_id, p_claim_token, p_claim_epoch);
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

-- 7. Region completion.
create or replace function v3.complete_claimed_region_preparation(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint,
  p_status text, p_usable_count integer, p_failure_code text
) returns boolean language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; ts timestamptz;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'region_preparation');
  if p_status is null or p_status not in ('ready', 'no_content') or p_usable_count is null or p_usable_count < 0
     or (p_status = 'ready' and p_usable_count < 1)
     or (p_status = 'no_content' and p_usable_count <> 0) then
    raise exception 'Invalid region preparation completion' using errcode = '23514';
  end if;
  ts := clock_timestamp();
  update v3.video_region_preparations set status = p_status, usable_count = p_usable_count,
    failure_code = p_failure_code, retryable = false, completed_at = ts, updated_at = ts
    where id = i.region_preparation_id;
  update v3.video_work_intents set state = 'completed', completed_at = ts, updated_at = ts where id = i.id;
  return true;
end $$;

-- 8. Admission. The API has already verified CurrentUser and resolved the current original
-- transcript; this rechecks ownership and the range, charges the learner's budget only when
-- the region is new, and admits at most one active intent per region.
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

  if found then
    if r.status = 'failed' and r.retryable then
      select coalesce(max(generation), 0) + 1 into gen from v3.video_work_intents
        where region_preparation_id = r.id and stage = 'region_preparation';
      update v3.video_region_preparations set status = 'pending', failure_code = null, retryable = false,
        completed_at = null, updated_at = now() where id = r.id returning * into r;
      insert into v3.video_work_intents (video_id, stage, generation, region_preparation_id)
        values (v.id, 'region_preparation', gen, r.id) returning id into intent;
      return jsonb_build_object('status', r.status, 'region_preparation_id', r.id, 'intent_id', intent,
                                'dispatch_now', true, 'usable_count', r.usable_count, 'retryable', false);
    end if;
    return jsonb_build_object('status', r.status, 'region_preparation_id', r.id, 'intent_id', null,
                              'dispatch_now', false, 'usable_count', r.usable_count, 'retryable', r.retryable);
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

revoke all on function v3.lock_current_preparation_claim(uuid, uuid, bigint) from public, anon, authenticated;
grant execute on function v3.lock_current_preparation_claim(uuid, uuid, bigint) to service_role;
revoke all on function v3.preparation_claim_covers_segment(text, uuid, uuid) from public, anon, authenticated;
grant execute on function v3.preparation_claim_covers_segment(text, uuid, uuid) to service_role;
revoke all on function v3.complete_claimed_region_preparation(uuid, uuid, bigint, text, integer, text)
  from public, anon, authenticated;
grant execute on function v3.complete_claimed_region_preparation(uuid, uuid, bigint, text, integer, text)
  to service_role;
revoke all on function v3.admit_region_preparation(uuid, uuid, uuid, uuid, uuid, text, text, integer, integer, integer)
  from public, anon, authenticated;
grant execute on function v3.admit_region_preparation(uuid, uuid, uuid, uuid, uuid, text, text, integer, integer, integer)
  to service_role;
