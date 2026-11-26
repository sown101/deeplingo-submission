-- ADR-020 phase 1: "My words" and the "I know this" quick check.
--
-- Saved words reuse v3.saved_concepts (the learner's own Concept save, content-owned per
-- DATA_AUTHORITY): saving is a request that only raises practice priority and never changes
-- mastery, skills or review. This adds the source of the save.
--
-- Known words are a new learner-owned table written only by v3.mark_concept_known, after a
-- known-check practice session whose every activity has an applied, fully correct
-- Assessment; the row keeps that session and Assessment. Learners read their own rows;
-- writes go through authenticated FastAPI routes (service role). Forward-only.

alter table v3.saved_concepts add column if not exists save_source text;
alter table v3.saved_concepts drop constraint if exists saved_concepts_save_source_check;
alter table v3.saved_concepts add constraint saved_concepts_save_source_check
  check (save_source is null or save_source in ('lookup', 'manual', 'occurrence'));

create table if not exists v3.learner_known_concepts (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  known_check_session_id uuid not null references v3.learning_sessions(id) on delete cascade,
  assessment_id uuid references v3.assessments(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, concept_id)
);

comment on table v3.learner_known_concepts is
  'ADR-020: words the learner proved they know in a quick check. Written only by '
  'v3.mark_concept_known; excluded from new practice. Not mastery or ReviewState.';

create index if not exists learner_known_concepts_user_language_idx
  on v3.learner_known_concepts (user_id, language_code, updated_at desc);
create index if not exists learner_known_concepts_session_idx
  on v3.learner_known_concepts (known_check_session_id);

alter table v3.learner_known_concepts enable row level security;
revoke all privileges on v3.learner_known_concepts from anon, authenticated;
grant select on v3.learner_known_concepts to authenticated;
grant all privileges on v3.learner_known_concepts to service_role;

drop policy if exists "Users can read own known concepts" on v3.learner_known_concepts;
create policy "Users can read own known concepts"
  on v3.learner_known_concepts for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- One active known check per learner and Concept. It reuses learning_sessions and
-- session_activities, like video learning.
create unique index if not exists learning_sessions_one_active_known_check_idx
  on v3.learning_sessions (user_id, (goal->>'concept_id'))
  where type = 'practice'
    and status in ('planned', 'active')
    and goal->>'origin' = 'known_check';

create or replace function v3.start_or_resume_known_check_session(
  p_user_id uuid,
  p_library_item_id uuid,
  p_video_id uuid,
  p_learning_object_id uuid,
  p_concept_id uuid,
  p_language_code text,
  p_support_language_code text,
  p_policy_version text,
  p_activity_types text[]
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_session v3.learning_sessions;
  v_enrichment jsonb;
begin
  if p_policy_version <> 'adr020-known-check-v1'
      or p_activity_types is null
      or cardinality(p_activity_types) < 1
      or cardinality(p_activity_types) > 2
      or not ('cloze' = any(p_activity_types))
      or exists (select 1 from unnest(p_activity_types) t where t not in ('cloze', 'dictation'))
      or (select count(distinct t) from unnest(p_activity_types) t) <> cardinality(p_activity_types) then
    raise exception 'known_check_conflict: invalid_selection';
  end if;
  if not exists (
    select 1 from v3.learner_videos lv
    join v3.videos v on v.id = lv.video_id
    where lv.id = p_library_item_id and lv.user_id = p_user_id
      and lv.video_id = p_video_id
      and v.original_language_code = p_language_code
      and v.learning_status = 'ready'
      and v.learning_prepared_language_code = p_support_language_code
  ) then
    raise exception 'known_check_conflict: library_or_readiness';
  end if;

  select * into v_session from v3.learning_sessions
  where user_id = p_user_id and type = 'practice'
    and status in ('planned', 'active')
    and goal->>'origin' = 'known_check'
    and goal->>'concept_id' = p_concept_id::text
  order by created_at limit 1;
  if v_session.id is not null then
    if v_session.goal->>'support_language_code' = p_support_language_code
        and v_session.goal->>'learning_object_id' = p_learning_object_id::text then
      return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
    end if;
    -- A check started elsewhere for the same word is replaced, never merged.
    update v3.learning_sessions set status = 'abandoned', updated_at = now()
    where id = v_session.id;
  end if;

  -- Same occurrence and enrichment checks as video learning.
  select coalesce(lo.raw_ai_diagnostics->'enrichments'->p_support_language_code,
                  lo.raw_ai_diagnostics->'enrichment')
    into v_enrichment
  from v3.learning_objects lo
  join v3.concepts c on c.id = lo.concept_id
  join v3.transcript_segments s on s.id = lo.transcript_segment_id
  join v3.video_transcripts t on t.id = s.transcript_id
  where lo.id = p_learning_object_id and lo.concept_id = p_concept_id
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
      or v_enrichment->>'concept_id' <> p_concept_id::text
      or v_enrichment->>'source_language_code' <> p_language_code
      or v_enrichment->>'target_language_code' <> p_support_language_code
      or btrim(coalesce(v_enrichment->>'contextual_meaning', '')) = ''
      or btrim(coalesce(v_enrichment->>'explanation', '')) = '' then
    raise exception 'known_check_conflict: unprepared_occurrence';
  end if;

  insert into v3.learning_sessions (
    user_id, language_code, type, status, goal, started_at
  ) values (
    p_user_id, p_language_code, 'practice', 'active',
    jsonb_build_object(
      'origin', 'known_check',
      'session_policy_version', p_policy_version,
      'video_id', p_video_id,
      'library_item_id', p_library_item_id,
      'learning_object_id', p_learning_object_id,
      'concept_id', p_concept_id,
      'support_language_code', p_support_language_code,
      'materialization', 'lazy',
      'max_activities', cardinality(p_activity_types)
    ), now()
  ) returning * into v_session;

  insert into v3.session_activities (
    session_id, concept_id, learning_object_id, activity_type, position,
    review_origin, prompt_payload, expected_response_payload, status
  )
  select v_session.id, p_concept_id, p_learning_object_id,
         t.activity_type::v3.activity_type, t.position::integer,
         false, '{}'::jsonb, null, 'planned'
  from unnest(p_activity_types) with ordinality as t(activity_type, position);

  return jsonb_build_object('created', true, 'session', to_jsonb(v_session));
exception
  when unique_violation then
    select * into v_session from v3.learning_sessions
    where user_id = p_user_id and type = 'practice'
      and status in ('planned', 'active')
      and goal->>'origin' = 'known_check'
      and goal->>'concept_id' = p_concept_id::text
    order by created_at limit 1;
    if v_session.id is not null
        and v_session.goal->>'support_language_code' = p_support_language_code
        and v_session.goal->>'learning_object_id' = p_learning_object_id::text then
      return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
    end if;
    raise;
end;
$$;

revoke all on function v3.start_or_resume_known_check_session(
  uuid, uuid, uuid, uuid, uuid, text, text, text, text[]
) from public, anon, authenticated;
grant execute on function v3.start_or_resume_known_check_session(
  uuid, uuid, uuid, uuid, uuid, text, text, text, text[]
) to service_role;

-- Marks a Concept known only when the learner's known-check session has an applied,
-- fully correct Assessment for every activity. Idempotent; never touches mastery,
-- skills or review (those already came from the normal assessment application).
create or replace function v3.mark_concept_known(p_user_id uuid, p_session_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_session v3.learning_sessions;
  v_total integer;
  v_passed integer;
  v_assessment_id uuid;
begin
  select * into v_session from v3.learning_sessions
  where id = p_session_id and user_id = p_user_id
    and type = 'practice' and goal->>'origin' = 'known_check'
  for update;
  if v_session.id is null then
    raise exception 'known_check_conflict: session';
  end if;

  select count(*) into v_total from v3.session_activities where session_id = v_session.id;
  -- Each activity counts once, by its latest applied Assessment.
  select count(*), max(latest.assessment_id::text)::uuid into v_passed, v_assessment_id
  from (
    select distinct on (sa.id) sa.id, a.id as assessment_id, a.overall_score
    from v3.session_activities sa
    join v3.attempts t on t.activity_id = sa.id and t.user_id = p_user_id
    join v3.assessments a on a.attempt_id = t.id
    join v3.assessment_applications aa on aa.assessment_id = a.id and aa.user_id = p_user_id
    where sa.session_id = v_session.id
    order by sa.id, aa.applied_at desc
  ) latest
  where latest.overall_score >= 1;

  if v_total < 1 or v_passed <> v_total then
    if v_session.status in ('planned', 'active') then
      update v3.learning_sessions set status = 'completed', completed_at = now(), updated_at = now()
      where id = v_session.id;
    end if;
    return jsonb_build_object('known', false);
  end if;

  insert into v3.learner_known_concepts (
    user_id, concept_id, language_code, known_check_session_id, assessment_id
  ) values (
    p_user_id, (v_session.goal->>'concept_id')::uuid, v_session.language_code,
    v_session.id, v_assessment_id
  )
  on conflict (user_id, concept_id) do update
    set known_check_session_id = excluded.known_check_session_id,
        assessment_id = excluded.assessment_id,
        updated_at = now();

  if v_session.status in ('planned', 'active') then
    update v3.learning_sessions set status = 'completed', completed_at = now(), updated_at = now()
    where id = v_session.id;
  end if;
  return jsonb_build_object('known', true, 'assessment_id', v_assessment_id);
end;
$$;

revoke all on function v3.mark_concept_known(uuid, uuid) from public, anon, authenticated;
grant execute on function v3.mark_concept_known(uuid, uuid) to service_role;

-- The first Evidence of a known check may create the Concept's first ReviewState, as
-- video learning does. Same function as v6a7 with the origin widened.
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
      and ls.type = 'practice' and ls.goal->>'origin' in ('video_learning', 'known_check')
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
