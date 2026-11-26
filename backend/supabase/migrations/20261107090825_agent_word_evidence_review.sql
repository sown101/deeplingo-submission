-- Owner decision 2026-11-07: paused words still earn evidence; only independent use updates FSRS.
-- Forward-only. No applied migration is modified. Service-only RPCs, no learner text stored.

create or replace function v3.complete_speaking_session(p_session_id uuid, p_uses jsonb, p_model text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  s v3.speaking_sessions%rowtype;
  item jsonb;
  target jsonb;
  cid uuid;
  used_at timestamptz;
  result jsonb := '[]'::jsonb;
begin
  select * into s from v3.speaking_sessions where id = p_session_id for update;
  if not found then return result; end if;
  if s.status in ('projecting', 'completed') then return s.events; end if;
  if s.status <> 'processing' then return result; end if;
  if s.expires_at <= now() then
    update v3.speaking_sessions set status = 'expired', error_code = 'expired' where id = s.id;
    return result;
  end if;
  if jsonb_typeof(p_uses) is distinct from 'array' or jsonb_array_length(p_uses) > 12 then
    raise exception using errcode = '22023', message = 'invalid_speaking_uses';
  end if;
  if (select count(*) from jsonb_array_elements(p_uses)) <>
     (select count(distinct value->>'concept_id') from jsonb_array_elements(p_uses)) then
    raise exception using errcode = '22023', message = 'duplicate_speaking_use';
  end if;
  for item in select value from jsonb_array_elements(p_uses) order by value->>'concept_id' loop
    if jsonb_typeof(item) is distinct from 'object'
       or (item - 'concept_id' - 'kind' - 'occurred_at') <> '{}'::jsonb
       or coalesce(item->>'kind', '') not in ('framed_use', 'spontaneous_use') then
      raise exception using errcode = '22023', message = 'invalid_speaking_use';
    end if;
    cid := (item->>'concept_id')::uuid;
    used_at := (item->>'occurred_at')::timestamptz;
    if used_at is null or used_at > s.occurred_at or used_at < s.occurred_at - interval '30 minutes' then
      raise exception using errcode = '22023', message = 'invalid_speaking_use_time';
    end if;
    select value into target from jsonb_array_elements(s.targets) where value->>'concept_id' = cid::text;
    if not found then
      raise exception using errcode = '22023', message = 'unselected_speaking_use';
    end if;
    -- Recheck ownership/current eligibility at commit, even if the word changed while queued.
    perform 1 from v3.saved_concepts sc join v3.concepts c on c.id = sc.concept_id
      where sc.user_id = s.user_id and sc.concept_id = cid
        and sc.status in ('active', 'backlog', 'suspended') and c.language_code = s.language_code
        and not exists (select 1 from v3.learner_known_concepts k
                        where k.user_id = s.user_id and k.concept_id = cid)
      for update of sc;
    if not found then continue; end if;
    insert into v3.target_events(user_id, concept_id, kind, outcome, event_key, context_key, judge, occurred_at)
      values (s.user_id, cid, item->>'kind', 'correct', 'l2:' || s.id::text || ':' || cid::text,
              s.context_key, jsonb_build_object('source', 'l2', 'version', 'l2-word-use-v1',
                                              'model', left(p_model, 120)), used_at)
      on conflict (user_id, event_key) do nothing;
    result := result || jsonb_build_array(jsonb_build_object(
      'concept_id', cid, 'text', target->>'text', 'kind', item->>'kind'));
  end loop;
  update v3.speaking_sessions set status = 'projecting', events = result where id = s.id;
  return result;
end;
$$;
revoke all on function v3.complete_speaking_session(uuid, jsonb, text) from public, anon, authenticated;
grant execute on function v3.complete_speaking_session(uuid, jsonb, text) to service_role;

-- The committed event, rather than the model output or client, authorizes a review.
create function v3.speaking_review_context(p_session_id uuid, p_user_id uuid, p_concept_id uuid)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'occurred_at', e.occurred_at,
    'eligible', coalesce(sc.status in ('active', 'backlog'), false)
      and not exists (select 1 from v3.learner_known_concepts k
                      where k.user_id = s.user_id and k.concept_id = p_concept_id),
    'review_state', to_jsonb(r))
  from v3.speaking_sessions s
  join v3.target_events e on e.user_id = s.user_id and e.concept_id = p_concept_id
    and e.event_key = 'l2:' || s.id::text || ':' || p_concept_id::text
    and e.kind = 'spontaneous_use' and e.outcome = 'correct'
  join lateral jsonb_array_elements(s.events) stored on stored->>'concept_id' = p_concept_id::text
    and stored->>'kind' = 'spontaneous_use' and not (stored ? 'review_status')
  left join v3.saved_concepts sc on sc.user_id = s.user_id and sc.concept_id = p_concept_id
  left join v3.review_states r on r.user_id = s.user_id and r.concept_id = p_concept_id
    and r.review_mode = 'concept_to_meaning'
  where s.id = p_session_id and s.user_id = p_user_id and s.status in ('projecting', 'completed');
$$;

-- Session marker + ReviewState + ReviewEvent commit together. A retry cannot count twice.
create function v3.commit_speaking_review(p_session_id uuid, p_user_id uuid, p_concept_id uuid, p_transition jsonb)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  s v3.speaking_sessions%rowtype;
  r v3.review_states%rowtype;
  stored jsonb;
  used_at timestamptz;
  previous jsonb := p_transition->'previous';
  target jsonb := p_transition->'next';
  event jsonb := p_transition->'event';
  eligible boolean;
  review_result text := 'skipped';
begin
  select * into s from v3.speaking_sessions where id = p_session_id and user_id = p_user_id for update;
  if not found or s.status not in ('projecting', 'completed') then return 'skipped'; end if;
  select value into stored from jsonb_array_elements(s.events) where value->>'concept_id' = p_concept_id::text;
  if not found or stored->>'kind' <> 'spontaneous_use' then return 'skipped'; end if;
  if stored ? 'review_status' then return 'duplicate'; end if;
  select occurred_at into used_at from v3.target_events
    where user_id = s.user_id and concept_id = p_concept_id
      and event_key = 'l2:' || s.id::text || ':' || p_concept_id::text
      and kind = 'spontaneous_use' and outcome = 'correct';
  if not found then return 'skipped'; end if;
  perform 1 from v3.saved_concepts sc where sc.user_id = s.user_id and sc.concept_id = p_concept_id
    and sc.status in ('active', 'backlog') for update;
  eligible := found and not exists (select 1 from v3.learner_known_concepts k
                                    where k.user_id = s.user_id and k.concept_id = p_concept_id);
  if eligible and p_transition is not null then
    if (previous->>'user_id')::uuid is distinct from s.user_id
       or (target->>'user_id')::uuid is distinct from s.user_id
       or (previous->>'concept_id')::uuid is distinct from p_concept_id
       or (target->>'concept_id')::uuid is distinct from p_concept_id
       or previous->>'review_mode' is distinct from 'concept_to_meaning'
       or target->>'review_mode' is distinct from 'concept_to_meaning'
       or event->>'review_mode' is distinct from 'concept_to_meaning'
       or (event->>'rating')::integer is distinct from 3
       or event->>'provenance' is distinct from 'speaking_use'
       or (event->>'attempt_id') is not null
       or (event->>'reviewed_at')::timestamptz is distinct from used_at
       or (target->>'last_reviewed_at')::timestamptz is distinct from used_at
       or (target->>'due_at')::timestamptz <= used_at
       or target->>'review_state_id' is distinct from previous->>'review_state_id'
       or event->>'review_state_id' is distinct from previous->>'review_state_id'
       or (target->>'version')::integer is distinct from (previous->>'version')::integer + 1
       or (target->>'reps')::integer is distinct from (previous->>'reps')::integer + 1
       or (target->>'lapses')::integer is distinct from (previous->>'lapses')::integer then
      raise exception 'invalid_speaking_review_transition';
    end if;
    select * into r from v3.review_states where user_id = s.user_id and concept_id = p_concept_id
      and review_mode = 'concept_to_meaning' for update;
    if not found then
      if p_transition->>'create' is distinct from 'true' or (previous->>'version')::integer <> 0
         or previous->>'fsrs_state' is distinct from 'new' or (previous->>'reps')::integer <> 0
         or (previous->>'lapses')::integer <> 0 or previous->>'last_reviewed_at' is not null then
        return 'conflict';
      end if;
      insert into v3.review_states(id, user_id, concept_id, review_mode, fsrs_state, due_at, version)
        values ((previous->>'review_state_id')::uuid, s.user_id, p_concept_id, 'concept_to_meaning', 'new', used_at, 0)
        on conflict (user_id, concept_id, review_mode) do nothing returning * into r;
      if not found then return 'conflict'; end if;
    elsif p_transition->>'create' is distinct from 'false' then
      return 'conflict';
    end if;
    if r.last_reviewed_at is null or r.last_reviewed_at < used_at then
      if r.id is distinct from (previous->>'review_state_id')::uuid
         or r.version is distinct from (previous->>'version')::integer then return 'conflict'; end if;
      update v3.review_states set
        stability = (target->>'stability')::numeric, difficulty = (target->>'difficulty')::numeric,
        elapsed_days = (target->>'elapsed_days')::integer, scheduled_days = (target->>'scheduled_days')::integer,
        reps = (target->>'reps')::integer, lapses = (target->>'lapses')::integer,
        fsrs_state = (target->>'fsrs_state')::v3.fsrs_state, due_at = (target->>'due_at')::timestamptz,
        last_reviewed_at = used_at, version = r.version + 1, updated_at = now()
        where id = r.id;
      insert into v3.review_events(review_state_id, review_mode, rating, provenance,
          previous_scheduling_state, resulting_scheduling_state, reviewed_at)
        values (r.id, 'concept_to_meaning', 3, 'speaking_use',
                event->'previous_scheduling_state', event->'resulting_scheduling_state', used_at);
      review_result := 'applied';
    end if;
  end if;
  update v3.speaking_sessions set events = (
    select jsonb_agg(case when value->>'concept_id' = p_concept_id::text
      then value || jsonb_build_object('review_status', review_result) else value end order by position)
    from jsonb_array_elements(s.events) with ordinality as items(value, position)) where id = s.id;
  return review_result;
end;
$$;
revoke all on function v3.speaking_review_context(uuid, uuid, uuid) from public, anon, authenticated;
revoke all on function v3.commit_speaking_review(uuid, uuid, uuid, jsonb) from public, anon, authenticated;
grant execute on function v3.speaking_review_context(uuid, uuid, uuid) to service_role;
grant execute on function v3.commit_speaking_review(uuid, uuid, uuid, jsonb) to service_role;
