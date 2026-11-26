-- Region preparation on development failed with SQLSTATE 57014 (statement timeout, 8 s for PostgREST's
-- `authenticator`): v3.enrich_claimed_occurrence looked up the dictionary entry with `where id::text = ...`, which cannot
-- use the primary key and scanned all ~332k rows of v3.dictionary_entries (290 MB, about 4.5 s per call on dev).
-- The function is replaced with the same signature, behaviour and grants; only that lookup changes to compare uuid to
-- uuid. Every other statement in it already uses an index (learning_objects, concepts, video_work_intents, videos,
-- transcript_segments primary keys; the sense-translation insert's conflict arbiter and foreign key check use the
-- primary keys of dictionary_sense_translations and dictionary_entries), so no index is added.
-- Forward-only. Backend-only (service role). Applying it to any environment needs the owner's approval for that
-- environment.

create or replace function v3.enrich_claimed_occurrence(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_learning_object_id uuid, p_enrichment jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; lo v3.learning_objects%rowtype; diag jsonb; langs jsonb; lang text;
        entry v3.dictionary_entries%rowtype; entry_id uuid;
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
  -- M1 S7d: a meaning translated from one dictionary sense is that sense in this language.
  if p_enrichment->>'meaning_provenance' = 'translated_from_sense'
     and char_length(btrim(coalesce(p_enrichment->>'contextual_meaning', ''))) between 1 and 160
     and coalesce(btrim(p_enrichment->'dictionary_sense'->>'sense_id'), '') <> '' then
    -- Compare uuid to uuid so the primary key is used. Only the canonical text form matched `id::text` before, so
    -- anything else still finds no entry instead of raising on the cast.
    entry_id := case when p_enrichment->'dictionary_sense'->>'dictionary_entry_id'
                          ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                     then (p_enrichment->'dictionary_sense'->>'dictionary_entry_id')::uuid end;
    select * into entry from v3.dictionary_entries where id = entry_id;
    if entry.id is not null then
      insert into v3.dictionary_sense_translations (dictionary_entry_id, sense_id, support_language_code,
        language_code, headword, part_of_speech, meaning, origin, prompt_version)
      values (entry.id, p_enrichment->'dictionary_sense'->>'sense_id', lang, entry.language_code, entry.headword,
        p_enrichment->'dictionary_sense'->>'pos', btrim(p_enrichment->>'contextual_meaning'), 'enrichment',
        p_enrichment->>'prompt_version')
      on conflict do nothing;
    end if;
  end if;
  return to_jsonb(lo);
end $$;

revoke all on function v3.enrich_claimed_occurrence(uuid, uuid, bigint, uuid, jsonb) from public, anon, authenticated;
grant execute on function v3.enrich_claimed_occurrence(uuid, uuid, bigint, uuid, jsonb) to service_role;
