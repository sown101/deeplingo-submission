-- A correct review answer closes only the open word_review requests for that word.
--
-- v3.submit_review_answer closed every open learner_study_requests row for the concept on a correct answer, so a
-- pronunciation_retry request for the same word was closed by a review that never practised pronunciation. The
-- function is re-created from 20261116100000_drop_known_concepts.sql with one change: the close statement now
-- also filters on kind = 'word_review'.

create or replace function v3.submit_review_answer(p_user_id uuid, p_concept_id uuid, p_transition jsonb, p_log jsonb)
 returns jsonb
 language plpgsql
 set search_path to ''
as $function$
declare
  existing v3.learner_activity_log%rowtype;
  r v3.review_states%rowtype;
  lang text;
  event_id text := p_log->>'client_event_id';
  pass_id text := nullif(p_log->>'source_id', '');
  previous jsonb := p_transition->'previous';
  target jsonb := p_transition->'next';
  event jsonb := p_transition->'event';
  reviewed timestamptz;
  scheduled boolean := false;
  next_due timestamptz;
  closed integer := 0;
begin
  if event_id is null or char_length(event_id) not between 1 and 200
     or p_log->>'kind' not in ('flashcard', 'choice', 'listening', 'cloze', 'pronunciation', 'writing', 'match',
                                 'order')
     or p_log->>'outcome' not in ('correct', 'incorrect', 'partial') then
    raise exception 'invalid_review_answer';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':' || event_id, 0));
  select * into existing from v3.learner_activity_log where user_id = p_user_id and client_event_id = event_id;
  if found then
    return jsonb_build_object('status', 'duplicate', 'outcome', existing.outcome, 'score', existing.score,
                              'detail', existing.detail);
  end if;

  select c.language_code into lang from v3.concepts c where c.id = p_concept_id;
  if lang is null or lang is distinct from p_log->>'language_code' then
    return jsonb_build_object('status', 'skipped');
  end if;
  perform 1 from v3.saved_concepts sc where sc.user_id = p_user_id and sc.concept_id = p_concept_id
    and sc.status in ('active', 'backlog') and sc.explicit for update;
  if not found then
    return jsonb_build_object('status', 'skipped');
  end if;

  if p_transition is not null and jsonb_typeof(p_transition) = 'object' and not exists (
       select 1 from v3.learner_activity_log l where l.user_id = p_user_id and l.item_type = 'concept'
          and l.item_id = p_concept_id::text and l.source_type = 'review_deck' and l.source_id = pass_id
          and l.detail->>'scheduled' = 'true') then
    reviewed := (event->>'reviewed_at')::timestamptz;
    if (previous->>'user_id')::uuid is distinct from p_user_id
       or (target->>'user_id')::uuid is distinct from p_user_id
       or (previous->>'concept_id')::uuid is distinct from p_concept_id
       or (target->>'concept_id')::uuid is distinct from p_concept_id
       or previous->>'review_mode' is distinct from 'concept_to_meaning'
       or target->>'review_mode' is distinct from 'concept_to_meaning'
       or event->>'review_mode' is distinct from 'concept_to_meaning'
       or event->>'provenance' is distinct from 'review_answer'
       or (event->>'rating')::integer not between 1 and 4
       or (target->>'last_reviewed_at')::timestamptz is distinct from reviewed
       or target->>'review_state_id' is distinct from previous->>'review_state_id'
       or event->>'review_state_id' is distinct from previous->>'review_state_id'
       or (target->>'version')::integer is distinct from (previous->>'version')::integer + 1 then
      raise exception 'invalid_review_transition';
    end if;
    select * into r from v3.review_states where user_id = p_user_id and concept_id = p_concept_id
      and review_mode = 'concept_to_meaning' for update;
    if not found then
      if p_transition->>'create' is distinct from 'true' or (previous->>'version')::integer <> 0 then
        return jsonb_build_object('status', 'conflict');
      end if;
      insert into v3.review_states(id, user_id, concept_id, review_mode, fsrs_state, due_at, version)
        values ((previous->>'review_state_id')::uuid, p_user_id, p_concept_id, 'concept_to_meaning', 'new', reviewed, 0)
        on conflict (user_id, concept_id, review_mode) do nothing returning * into r;
      if not found then return jsonb_build_object('status', 'conflict'); end if;
    elsif p_transition->>'create' is distinct from 'false' then
      return jsonb_build_object('status', 'conflict');
    end if;
    if r.id is distinct from (previous->>'review_state_id')::uuid
       or r.version is distinct from (previous->>'version')::integer then
      return jsonb_build_object('status', 'conflict');
    end if;
    update v3.review_states set
      stability = (target->>'stability')::numeric, difficulty = (target->>'difficulty')::numeric,
      elapsed_days = (target->>'elapsed_days')::integer, scheduled_days = (target->>'scheduled_days')::integer,
      reps = (target->>'reps')::integer, lapses = (target->>'lapses')::integer,
      fsrs_state = (target->>'fsrs_state')::v3.fsrs_state, due_at = (target->>'due_at')::timestamptz,
      last_reviewed_at = reviewed, version = r.version + 1, updated_at = now()
      where id = r.id;
    insert into v3.review_events(review_state_id, review_mode, rating, provenance,
        previous_scheduling_state, resulting_scheduling_state, reviewed_at)
      values (r.id, 'concept_to_meaning', (event->>'rating')::integer, 'review_answer',
              event->'previous_scheduling_state', event->'resulting_scheduling_state', reviewed);
    scheduled := true;
    next_due := (target->>'due_at')::timestamptz;
  else
    select rs.due_at into next_due from v3.review_states rs where rs.user_id = p_user_id
      and rs.concept_id = p_concept_id and rs.review_mode = 'concept_to_meaning';
  end if;

  insert into v3.learner_activity_log(user_id, language_code, client_event_id, kind, item_type, item_id, source_type,
                                      source_id, outcome, score, detail)
    values (p_user_id, lang, event_id, p_log->>'kind', 'concept', p_concept_id::text, 'review_deck', pass_id,
            p_log->>'outcome', (p_log->>'score')::numeric,
            coalesce(p_log->'detail', '{}'::jsonb)
              || jsonb_build_object('scheduled', scheduled, 'next_review_at', next_due));
  if p_log->>'outcome' = 'correct' then
    update v3.learner_study_requests set status = 'done', closed_at = now()
     where user_id = p_user_id and language_code = lang and item_type = 'concept'
       and item_id = p_concept_id::text and kind = 'word_review' and status = 'open';
    get diagnostics closed = row_count;
  end if;
  return jsonb_build_object('status', case when scheduled then 'applied' else 'graded' end,
                            'next_review_at', next_due, 'requests_closed', closed);
end $function$;

revoke all on function v3.submit_review_answer(uuid, uuid, jsonb, jsonb) from public, anon, authenticated;
grant execute on function v3.submit_review_answer(uuid, uuid, jsonb, jsonb) to service_role;
