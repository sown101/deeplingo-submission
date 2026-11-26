-- A26 (owner decision 2026-10-21: a claimed review RPC): under a worker claim, an enrichment answer of
-- "no offered dictionary sense fits" (ADR-017) must exclude one occurrence and record it for review.
-- `enrich_claimed_occurrence` can only write a meaning, so the review-only write failed (KeyError ->
-- unknown_failure) and took the whole Video or region preparation down with it.
--
-- This function records that review under the same fence as `enrich_claimed_occurrence`: it locks the
-- current claim, stays inside the claimed Video and region, and merges from the LOCKED row, never from a
-- worker's earlier snapshot. It withdraws this language's meaning (per-language map and the legacy
-- `enrichment` field when it is this language) and stores the review under `dictionary_review`. As with
-- meanings (M1 S7b), a meaning of the same prompt version that another claim stored first is kept.
-- Forward-only; no data is rewritten.

create or replace function v3.record_claimed_sense_review(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_learning_object_id uuid,
  p_target_language_code text, p_review jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; lo v3.learning_objects%rowtype; diag jsonb; langs jsonb; lang text;
begin
  i := v3.lock_current_preparation_claim(p_intent_id, p_claim_token, p_claim_epoch);
  select * into lo from v3.learning_objects where id = p_learning_object_id and video_id = i.video_id for update;
  if not found then raise exception 'Occurrence outside claimed Video' using errcode = '23514'; end if;
  if not v3.preparation_claim_covers_segment(i.stage, i.region_preparation_id, lo.transcript_segment_id) then
    raise exception 'Occurrence outside claimed region' using errcode = '23514';
  end if;
  lang := btrim(coalesce(p_target_language_code, ''));
  if lang = '' or jsonb_typeof(p_review) is distinct from 'object'
     or p_review->>'status' is distinct from 'no_matching_sense'
     or p_review->>'concept_id' is distinct from lo.concept_id::text
     or coalesce(btrim(p_review->>'prompt_version'), '') = ''
     or jsonb_typeof(p_review->'offered_sense_ids') is distinct from 'array'
     or not exists (select 1 from v3.concepts where id = lo.concept_id and sense_key = p_review->>'concept_sense_key') then
    raise exception 'Invalid claimed sense review' using errcode = '23514';
  end if;
  -- Merge from the LOCKED current JSONB, not the earlier read-modify-write snapshot.
  diag := coalesce(lo.raw_ai_diagnostics, '{}'::jsonb);
  langs := coalesce(diag->'enrichments', '{}'::jsonb);
  if diag->'enrichment'->>'target_language_code' is not null then
    langs := jsonb_build_object(diag->'enrichment'->>'target_language_code', diag->'enrichment') || langs;
  end if;
  if langs->lang->>'concept_id' = lo.concept_id::text
     and langs->lang->>'concept_sense_key' = p_review->>'concept_sense_key'
     and langs->lang->>'prompt_version' = p_review->>'prompt_version' then
    return to_jsonb(lo);  -- another claim stored a meaning of this version first; keep it
  end if;
  diag := diag || jsonb_build_object(
    'enrichments', langs - lang,
    'dictionary_review', coalesce(diag->'dictionary_review', '{}'::jsonb) || jsonb_build_object(lang, p_review));
  if diag->'enrichment'->>'target_language_code' = lang then
    diag := diag - 'enrichment';
  end if;
  update v3.learning_objects set raw_ai_diagnostics = diag, updated_at = clock_timestamp()
    where id = lo.id returning * into lo;
  return to_jsonb(lo);
end $$;

revoke all on function v3.record_claimed_sense_review(uuid, uuid, bigint, uuid, text, jsonb) from public, anon, authenticated;
grant execute on function v3.record_claimed_sense_review(uuid, uuid, bigint, uuid, text, jsonb) to service_role;
