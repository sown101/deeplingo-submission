-- M1 S7d: Quick review completion (owner decisions 2026-10-19). Forward-only.
--
-- 1. `v3.dictionary_sense_translations`: a dictionary sense rendered in a support language, stored
--    once (first writer wins) so Quick review shows meanings in the learner's support language without
--    a model call. Seeded from occurrence meanings that were translated from a dictionary sense; filled
--    by claimed enrichment (below) and by the application after lookups and searches. Global content.
-- 2. `v3.learner_looked_up_concepts`: a word the learner looked up and the server resolved to one
--    dictionary sense (its Concept). A Quick review candidate without saving it to My Words; kept 90
--    days after the last lookup, like the practice log.
-- 3. `v3.learner_quick_review_skips`: "Bỏ mục này". The word leaves Quick review only: no Attempt,
--    no FSRS change, not marked known. The learner brings it back from My Words.
-- 4. The batch RPC accepts looked-up words as new cards, leaves skipped words out, and accepts the
--    "choose the meaning" form (no sentence) next to "choose the meaning in the sentence".
-- 5. `v3.skip_quick_review_item`: records the skip and closes that question if it was not answered.
-- 6. Claimed enrichment also stores its sense translation; the purge also removes expired lookups.

-- 1. Sense translations ---------------------------------------------------------------------------
create table if not exists v3.dictionary_sense_translations (
  dictionary_entry_id uuid not null references v3.dictionary_entries(id) on delete cascade,
  sense_id text not null check (btrim(sense_id) <> '' and char_length(sense_id) <= 80),
  support_language_code text not null check (btrim(support_language_code) <> ''),
  language_code text not null check (btrim(language_code) <> ''),
  headword text not null check (btrim(headword) <> ''),
  part_of_speech text,
  meaning text not null check (btrim(meaning) <> '' and char_length(meaning) <= 160),
  origin text not null check (origin in ('enrichment', 'lookup', 'search')),
  prompt_version text not null check (btrim(prompt_version) <> ''),
  created_at timestamptz not null default now(),
  primary key (dictionary_entry_id, sense_id, support_language_code)
);
create index if not exists dictionary_sense_translations_pool_idx
  on v3.dictionary_sense_translations (language_code, support_language_code, created_at desc);
comment on table v3.dictionary_sense_translations is
  'M1 S7d: a dictionary sense in a support language (first writer wins); global content, service role only.';
alter table v3.dictionary_sense_translations enable row level security;
revoke all privileges on v3.dictionary_sense_translations from public, anon, authenticated;
grant all privileges on v3.dictionary_sense_translations to service_role;

insert into v3.dictionary_sense_translations (dictionary_entry_id, sense_id, support_language_code, language_code,
  headword, part_of_speech, meaning, origin, prompt_version)
select distinct on (d.id, e.value->'dictionary_sense'->>'sense_id', e.key)
  d.id, e.value->'dictionary_sense'->>'sense_id', e.key, d.language_code, d.headword,
  e.value->'dictionary_sense'->>'pos', btrim(e.value->>'contextual_meaning'), 'enrichment', e.value->>'prompt_version'
from v3.learning_objects lo
  cross join lateral jsonb_each(case when jsonb_typeof(lo.raw_ai_diagnostics->'enrichments') = 'object'
                                     then lo.raw_ai_diagnostics->'enrichments' else '{}'::jsonb end) e
  join v3.dictionary_entries d
    on d.id::text = e.value->'dictionary_sense'->>'dictionary_entry_id'
where e.value->>'meaning_provenance' = 'translated_from_sense'
  and coalesce(btrim(e.value->'dictionary_sense'->>'sense_id'), '') <> ''
  and char_length(btrim(coalesce(e.value->>'contextual_meaning', ''))) between 1 and 160
  and coalesce(btrim(e.value->>'prompt_version'), '') <> ''
order by d.id, e.value->'dictionary_sense'->>'sense_id', e.key, lo.created_at
on conflict do nothing;

-- 2. Looked-up words --------------------------------------------------------------------------------
create table if not exists v3.learner_looked_up_concepts (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  source text not null check (source in ('workspace', 'companion')),
  lookup_count integer not null default 1 check (lookup_count >= 1),
  first_looked_up_at timestamptz not null default now(),
  last_looked_up_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '90 days',
  primary key (user_id, concept_id),
  constraint learner_looked_up_concepts_expiry_chk check (expires_at > last_looked_up_at)
);
create index if not exists learner_looked_up_concepts_recent_idx
  on v3.learner_looked_up_concepts (user_id, last_looked_up_at desc);
comment on table v3.learner_looked_up_concepts is
  'M1 S7d: words a learner looked up, resolved to one dictionary sense; Quick review candidates; 90 days.';
alter table v3.learner_looked_up_concepts enable row level security;
revoke all privileges on v3.learner_looked_up_concepts from public, anon, authenticated;
grant select on v3.learner_looked_up_concepts to authenticated;
grant all privileges on v3.learner_looked_up_concepts to service_role;
drop policy if exists "Users can read own looked-up words" on v3.learner_looked_up_concepts;
create policy "Users can read own looked-up words" on v3.learner_looked_up_concepts for select to authenticated
  using ((select auth.uid()) = user_id and expires_at > now());

create or replace function v3.record_looked_up_concept(p_user_id uuid, p_concept_id uuid, p_source text)
returns void language plpgsql security invoker set search_path = '' as $$
begin
  if p_source is null or p_source not in ('workspace', 'companion') then
    raise exception 'Invalid lookup source' using errcode = '22023';
  end if;
  insert into v3.learner_looked_up_concepts (user_id, concept_id, source)
  values (p_user_id, p_concept_id, p_source)
  on conflict (user_id, concept_id) do update set
    lookup_count = v3.learner_looked_up_concepts.lookup_count + 1,
    last_looked_up_at = now(), expires_at = now() + interval '90 days';
end $$;
revoke all on function v3.record_looked_up_concept(uuid, uuid, text) from public, anon, authenticated;
grant execute on function v3.record_looked_up_concept(uuid, uuid, text) to service_role;

-- 3. Skips ----------------------------------------------------------------------------------------
create table if not exists v3.learner_quick_review_skips (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, concept_id)
);
comment on table v3.learner_quick_review_skips is
  'M1 S7d: words the learner removed from Quick review (not known, no FSRS change); removable by the learner.';
alter table v3.learner_quick_review_skips enable row level security;
revoke all privileges on v3.learner_quick_review_skips from public, anon, authenticated;
grant select on v3.learner_quick_review_skips to authenticated;
grant all privileges on v3.learner_quick_review_skips to service_role;
drop policy if exists "Users can read own Quick review skips" on v3.learner_quick_review_skips;
create policy "Users can read own Quick review skips" on v3.learner_quick_review_skips for select to authenticated
  using ((select auth.uid()) = user_id);

-- 4. Batch RPC --------------------------------------------------------------------------------------
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
    -- "Choose the meaning" has no sentence; "in the sentence" has exactly one. Missing fields fail.
    if coalesce(
        (v_meaning_form and (v_example is not null or v_object is not null))
        or (not v_meaning_form and (v_example is null) = (v_object is null))
        or coalesce(v_prov->>'question_form', '') not in ('meaning', 'meaning_in_sentence')
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
        and review_mode = 'concept_to_meaning';
      if v_state.id is null or v_state.version is distinct from (v_item->>'source_review_state_version')::integer
          or v_state.due_at > now() then
        raise exception 'quick_review_conflict: review_state';
      end if;
    else
      -- A new card: a saved or recently looked-up, not known word with no concept_to_meaning state yet.
      if not (exists (select 1 from v3.saved_concepts sc where sc.user_id = p_user_id and sc.concept_id = v_concept)
              or exists (select 1 from v3.learner_looked_up_concepts l
                         where l.user_id = p_user_id and l.concept_id = v_concept and l.expires_at > now()))
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

-- 5. Skip one question --------------------------------------------------------------------------------
create or replace function v3.skip_quick_review_item(p_user_id uuid, p_session_id uuid, p_activity_id uuid)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare s v3.learning_sessions; a v3.session_activities; answered boolean;
begin
  select * into s from v3.learning_sessions
    where id = p_session_id and user_id = p_user_id and goal->>'origin' = 'quick_review';
  if s.id is null then
    raise exception 'quick_review_conflict: session' using errcode = 'P0002';
  end if;
  select * into a from v3.session_activities where id = p_activity_id and session_id = s.id for update;
  if a.id is null or a.concept_id is null then
    raise exception 'quick_review_conflict: activity' using errcode = 'P0002';
  end if;
  insert into v3.learner_quick_review_skips (user_id, concept_id) values (p_user_id, a.concept_id)
    on conflict do nothing;
  answered := exists (select 1 from v3.attempts t where t.activity_id = a.id and t.user_id = p_user_id);
  if not answered and a.status = 'active' then
    update v3.session_activities set status = 'skipped', updated_at = now() where id = a.id;
  end if;
  return jsonb_build_object('concept_id', a.concept_id, 'question_closed', not answered);
end $$;
revoke all on function v3.skip_quick_review_item(uuid, uuid, uuid) from public, anon, authenticated;
grant execute on function v3.skip_quick_review_item(uuid, uuid, uuid) to service_role;

-- 6a. Claimed enrichment also stores its sense translation (first writer wins) ---------------------
create or replace function v3.enrich_claimed_occurrence(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_learning_object_id uuid, p_enrichment jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; lo v3.learning_objects%rowtype; diag jsonb; langs jsonb; lang text;
        entry v3.dictionary_entries%rowtype;
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
    select * into entry from v3.dictionary_entries
      where id::text = p_enrichment->'dictionary_sense'->>'dictionary_entry_id';
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

-- 6b. The purge also removes expired lookups ---------------------------------------------------------
create or replace function v3.purge_expired_learner_data(p_limit integer default 1000)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare practice integer; memory integer; lookups integer;
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
  delete from v3.learner_looked_up_concepts where (user_id, concept_id) in (
    select user_id, concept_id from v3.learner_looked_up_concepts where expires_at <= now() limit p_limit);
  get diagnostics lookups = row_count;
  return jsonb_build_object('practice_events', practice, 'companion_memory', memory, 'looked_up', lookups);
end $$;
