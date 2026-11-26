-- Restructure phase 2 (docs/architecture/TARGET_DESIGN.md section 5, PRD 8.10): one review engine with a deck per
-- language, and grammar results without FSRS.
--   * review_states.language_code: the deck a card belongs to, always the language of its concept (backfilled here,
--     kept by a trigger for every writer, including the older session RPCs).
--   * learner_grammar_progress: per grammar point, whether the lesson was learned, how many exercises were done and
--     the last correct one. Backfilled from learner_grammar_review_results, which is no longer written.
--   * review_deck_counts / review_deck_cards / review_answer_context: read the learner's decks.
--   * submit_review_answer: the graded answer, its FSRS change (at most once per card and review pass) and its
--     learning-log row in one transaction; a retried client_event_id returns the stored result.
--   * record_grammar_answer / record_grammar_lesson: the grammar result, its progress row and its learning-log row in
--     one transaction; a correct answer closes the open grammar_redo requests for that point.
-- Additive and forward-only: one new column with a backfill, one new table, new functions. Backend-only (service
-- role). Applying it to any environment needs the owner's approval for that environment.

-- 1. A deck per language ---------------------------------------------------------------------------------------

alter table v3.review_states add column if not exists language_code text
  references v3.languages(code) on delete restrict;

update v3.review_states as r
   set language_code = c.language_code
  from v3.concepts as c
 where c.id = r.concept_id and r.language_code is distinct from c.language_code;

create or replace function v3.review_states_language()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  select c.language_code into new.language_code from v3.concepts c where c.id = new.concept_id;
  return new;
end $$;

drop trigger if exists review_states_language on v3.review_states;
create trigger review_states_language before insert or update of concept_id, language_code on v3.review_states
  for each row execute function v3.review_states_language();

alter table v3.review_states alter column language_code set not null;

create index if not exists review_states_deck_idx
  on v3.review_states (user_id, language_code, review_mode, due_at);
create index if not exists learner_activity_log_item_idx
  on v3.learner_activity_log (user_id, item_type, item_id, occurred_at desc) where item_type is not null;

comment on column v3.review_states.language_code is
  'Restructure phase 2: the review deck (one per language) the card belongs to; always its concept''s language.';

-- 2. Grammar progress (no FSRS) --------------------------------------------------------------------------------

create table if not exists v3.learner_grammar_progress (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  grammar_key text not null,
  lesson_learned_at timestamptz,
  attempts integer not null default 0,
  correct_count integer not null default 0,
  last_attempt_at timestamptz,
  last_correct_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (user_id, language_code, grammar_key),
  constraint learner_grammar_progress_key_check check (char_length(grammar_key) between 1 and 80),
  constraint learner_grammar_progress_counts_check check (attempts >= 0 and correct_count between 0 and attempts)
);

comment on table v3.learner_grammar_progress is
  'Restructure phase 2: the learner''s grammar results per point (lesson learned, exercises done, last correct). No FSRS. Backend-only.';

alter table v3.learner_grammar_progress enable row level security;
revoke all privileges on v3.learner_grammar_progress from public, anon, authenticated;
grant all privileges on v3.learner_grammar_progress to service_role;

insert into v3.learner_grammar_progress
  (user_id, language_code, grammar_key, attempts, correct_count, last_attempt_at, last_correct_at)
select r.user_id, r.language_code, r.grammar_key, count(*), count(*) filter (where r.is_correct),
       max(r.created_at), max(r.created_at) filter (where r.is_correct)
  from v3.learner_grammar_review_results r
 group by r.user_id, r.language_code, r.grammar_key
on conflict (user_id, language_code, grammar_key) do nothing;

-- 3. Reading the decks -----------------------------------------------------------------------------------------
-- A card is a saved word (active or legacy backlog, saved on purpose, not known) with its concept_to_meaning state;
-- a saved word without a state is a new card. Words the learner took out of review (learner_quick_review_skips) stay out of
-- the deck unless the learner picks them.

create or replace function v3.review_deck_counts(p_user_id uuid)
returns table(language_code text, due_count bigint, new_count bigint, total_count bigint)
language sql stable security invoker set search_path = '' as $$
  select c.language_code,
         count(*) filter (where r.id is not null and r.due_at <= now()),
         count(*) filter (where r.id is null),
         count(*)
    from v3.saved_concepts sc
    join v3.concepts c on c.id = sc.concept_id
    left join v3.review_states r
      on r.user_id = sc.user_id and r.concept_id = sc.concept_id and r.review_mode = 'concept_to_meaning'
   where sc.user_id = p_user_id and sc.status in ('active', 'backlog') and sc.explicit
     and not exists (select 1 from v3.learner_known_concepts k where k.user_id = sc.user_id and k.concept_id = sc.concept_id)
     and not exists (select 1 from v3.learner_quick_review_skips q where q.user_id = sc.user_id and q.concept_id = sc.concept_id)
   group by c.language_code;
$$;

-- Due cards first (earliest due), then new cards (newest save first). With p_concept_ids, exactly those saved words.
create or replace function v3.review_deck_cards(p_user_id uuid, p_language_code text, p_limit integer,
                                                p_concept_ids uuid[] default null)
returns table(concept_id uuid, due_at timestamptz, is_new boolean)
language sql stable security invoker set search_path = '' as $$
  select sc.concept_id, r.due_at, r.id is null
    from v3.saved_concepts sc
    join v3.concepts c on c.id = sc.concept_id and c.language_code = p_language_code
    left join v3.review_states r
      on r.user_id = sc.user_id and r.concept_id = sc.concept_id and r.review_mode = 'concept_to_meaning'
   where sc.user_id = p_user_id and sc.status in ('active', 'backlog') and sc.explicit
     and not exists (select 1 from v3.learner_known_concepts k where k.user_id = sc.user_id and k.concept_id = sc.concept_id)
     and case when p_concept_ids is null then (r.id is null or r.due_at <= now()) and not exists (
                select 1 from v3.learner_quick_review_skips q where q.user_id = sc.user_id and q.concept_id = sc.concept_id)
              else sc.concept_id = any(p_concept_ids) end
   order by r.id is null, r.due_at, sc.created_at desc
   limit least(greatest(coalesce(p_limit, 20), 1), 200);
$$;

create or replace function v3.review_answer_context(p_user_id uuid, p_concept_id uuid, p_pass_id text)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'language_code', (select c.language_code from v3.concepts c where c.id = p_concept_id),
    'eligible', exists (select 1 from v3.saved_concepts sc where sc.user_id = p_user_id and sc.concept_id = p_concept_id
                          and sc.status in ('active', 'backlog') and sc.explicit)
      and not exists (select 1 from v3.learner_known_concepts k where k.user_id = p_user_id and k.concept_id = p_concept_id),
    'review_state', (select to_jsonb(r) from v3.review_states r where r.user_id = p_user_id
                       and r.concept_id = p_concept_id and r.review_mode = 'concept_to_meaning'),
    'scheduled_in_pass', p_pass_id is not null and exists (
      select 1 from v3.learner_activity_log l where l.user_id = p_user_id and l.item_type = 'concept'
         and l.item_id = p_concept_id::text and l.source_type = 'review_deck' and l.source_id = p_pass_id
         and l.detail->>'scheduled' = 'true'),
    'last_result', (select jsonb_build_object('outcome', l.outcome, 'fast', l.detail->'fast')
                      from v3.learner_activity_log l where l.user_id = p_user_id and l.item_type = 'concept'
                       and l.item_id = p_concept_id::text and l.source_type = 'review_deck'
                     order by l.occurred_at desc limit 1));
$$;

-- 4. One answer: grade + FSRS + log --------------------------------------------------------------------------------

create or replace function v3.submit_review_answer(p_user_id uuid, p_concept_id uuid, p_transition jsonb, p_log jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
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
     or p_log->>'kind' not in ('flashcard', 'choice', 'listening', 'cloze', 'pronunciation', 'writing')
     or p_log->>'outcome' not in ('correct', 'incorrect', 'partial') then
    raise exception 'invalid_review_answer';
  end if;
  -- One answer at a time per (learner, event): a concurrent retry waits and then finds the stored row.
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
  if not found or exists (select 1 from v3.learner_known_concepts k
                          where k.user_id = p_user_id and k.concept_id = p_concept_id) then
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
       and item_id = p_concept_id::text and status = 'open';
    get diagnostics closed = row_count;
  end if;
  return jsonb_build_object('status', case when scheduled then 'applied' else 'graded' end,
                            'next_review_at', next_due, 'requests_closed', closed);
end $$;

-- 5. Grammar answers and lessons -----------------------------------------------------------------------------------

create or replace function v3.record_grammar_answer(p_user_id uuid, p_language_code text, p_grammar_key text,
                                                    p_log jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  existing v3.learner_activity_log%rowtype;
  event_id text := p_log->>'client_event_id';
  correct boolean := p_log->>'outcome' = 'correct';
  closed integer := 0;
begin
  if event_id is null or char_length(event_id) not between 1 and 200
     or p_log->>'outcome' not in ('correct', 'incorrect') or char_length(p_grammar_key) not between 1 and 80 then
    raise exception 'invalid_grammar_answer';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':' || event_id, 0));
  select * into existing from v3.learner_activity_log where user_id = p_user_id and client_event_id = event_id;
  if found then
    return jsonb_build_object('status', 'duplicate', 'outcome', existing.outcome, 'detail', existing.detail);
  end if;
  insert into v3.learner_activity_log(user_id, language_code, client_event_id, kind, item_type, item_id, source_type,
                                      outcome, detail)
    values (p_user_id, p_language_code, event_id, 'grammar_exercise', 'grammar_point', p_grammar_key, 'notebook',
            p_log->>'outcome', coalesce(p_log->'detail', '{}'::jsonb));
  insert into v3.learner_grammar_progress as g
      (user_id, language_code, grammar_key, attempts, correct_count, last_attempt_at, last_correct_at)
    values (p_user_id, p_language_code, p_grammar_key, 1, case when correct then 1 else 0 end, now(),
            case when correct then now() end)
    on conflict (user_id, language_code, grammar_key) do update set
      attempts = g.attempts + 1, correct_count = g.correct_count + excluded.correct_count,
      last_attempt_at = excluded.last_attempt_at, last_correct_at = coalesce(excluded.last_correct_at, g.last_correct_at),
      updated_at = now();
  if correct then
    update v3.learner_study_requests set status = 'done', closed_at = now()
     where user_id = p_user_id and language_code = p_language_code and item_type = 'grammar_point'
       and item_id = p_grammar_key and status = 'open';
    get diagnostics closed = row_count;
  end if;
  return jsonb_build_object('status', 'recorded', 'requests_closed', closed);
end $$;

create or replace function v3.record_grammar_lesson(p_user_id uuid, p_language_code text, p_grammar_key text,
                                                    p_client_event_id text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare learned timestamptz;
begin
  if p_client_event_id is null or char_length(p_client_event_id) not between 1 and 200
     or char_length(p_grammar_key) not between 1 and 80 then
    raise exception 'invalid_grammar_lesson';
  end if;
  insert into v3.learner_activity_log(user_id, language_code, client_event_id, kind, item_type, item_id, source_type,
                                      outcome)
    values (p_user_id, p_language_code, p_client_event_id, 'grammar_lesson', 'grammar_point', p_grammar_key,
            'notebook', 'done')
    on conflict (user_id, client_event_id) do nothing;
  insert into v3.learner_grammar_progress as g (user_id, language_code, grammar_key, lesson_learned_at)
    values (p_user_id, p_language_code, p_grammar_key, now())
    on conflict (user_id, language_code, grammar_key) do update set
      lesson_learned_at = coalesce(g.lesson_learned_at, excluded.lesson_learned_at), updated_at = now()
    returning g.lesson_learned_at into learned;
  return jsonb_build_object('status', 'recorded', 'lesson_learned_at', learned);
end $$;

-- 6. Backend-only ------------------------------------------------------------------------------------------------

revoke all on function v3.review_states_language() from public, anon, authenticated;
revoke all on function v3.review_deck_counts(uuid) from public, anon, authenticated;
revoke all on function v3.review_deck_cards(uuid, text, integer, uuid[]) from public, anon, authenticated;
revoke all on function v3.review_answer_context(uuid, uuid, text) from public, anon, authenticated;
revoke all on function v3.submit_review_answer(uuid, uuid, jsonb, jsonb) from public, anon, authenticated;
revoke all on function v3.record_grammar_answer(uuid, text, text, jsonb) from public, anon, authenticated;
revoke all on function v3.record_grammar_lesson(uuid, text, text, text) from public, anon, authenticated;
grant execute on function v3.review_deck_counts(uuid) to service_role;
grant execute on function v3.review_deck_cards(uuid, text, integer, uuid[]) to service_role;
grant execute on function v3.review_answer_context(uuid, uuid, text) to service_role;
grant execute on function v3.submit_review_answer(uuid, uuid, jsonb, jsonb) to service_role;
grant execute on function v3.record_grammar_answer(uuid, text, text, jsonb) to service_role;
grant execute on function v3.record_grammar_lesson(uuid, text, text, text) to service_role;
