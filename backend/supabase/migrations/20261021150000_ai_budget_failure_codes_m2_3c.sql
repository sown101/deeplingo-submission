-- M2.3c DRAFT — NOT APPLIED ANYWHERE. Depends on 20261021130000 (M2.3a) and 20261021140000 (M2.3b). Owner approval
-- and a development rollback check are required before it is applied, as for every migration here.
-- Design: docs/product/M2_3_COST_CAPS_DESIGN.md sections 8-9.
--
-- Two persisted Content failure codes for the cost budget (design section 8):
-- - budget_exhausted (permanent): the region or video budget refused a request, so the work stopped with nothing
--   unsent; a retry would be refused again.
-- - budget_unavailable (transient): the ledger could not confirm a reservation; nothing was sent, a retry may succeed.
-- The codes must be allowed by the work-intent constraint AND by the failure RPC, or recording the failure is refused.
-- Only widens the lists: existing rows still satisfy the constraint.

alter table v3.video_work_intents drop constraint video_work_failure_metadata_chk;
alter table v3.video_work_intents add constraint video_work_failure_metadata_chk check (
  (failure_class is null and failure_code is null and last_error_at is null)
  or (failure_class is not null and failure_class in ('transient', 'permanent', 'unknown')
    and failure_code is not null and failure_code in (
      'transient_timeout', 'transient_network', 'provider_rate_limit', 'provider_temporary',
      'database_temporary', 'content_unavailable', 'validation_failed', 'invariant_violation',
      'configuration_error', 'unknown_failure', 'lease_lost', 'retry_exhausted',
      'budget_exhausted', 'budget_unavailable')
    and last_error_at is not null));

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
       'configuration_error', 'unknown_failure', 'budget_exhausted', 'budget_unavailable')
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


notify pgrst, 'reload schema';
