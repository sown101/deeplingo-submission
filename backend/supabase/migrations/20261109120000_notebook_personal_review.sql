-- Notebook redesign: the learner's own marks on a word, cached pictures, and the memory rating from flashcards.

alter table v3.saved_concepts
  add column if not exists favorite boolean not null default false,
  -- The learner's own view of whether they can use a word. It never changes the evidence-based rung.
  add column if not exists self_usage text
    constraint saved_concepts_self_usage_check check (self_usage in ('not_yet', 'with_help', 'on_my_own'));

create index if not exists dictionary_entries_hsk_idx on v3.dictionary_entries ((provider_metadata->>'hsk'), normalized_headword)
  where provider_metadata ? 'hsk';
create index if not exists dictionary_entries_cefr_j_idx on v3.dictionary_entries ((provider_metadata->>'cefr_j'), normalized_headword)
  where provider_metadata ? 'cefr_j';

-- One picture per concept, shared between learners; holds no learner data.
create table if not exists v3.concept_images (
  concept_id uuid primary key references v3.concepts(id) on delete cascade,
  image_url text not null,
  thumbnail_url text,
  title text,
  creator text,
  license text,
  source_url text,
  search_term text not null,
  result_index integer not null default 0 check (result_index >= 0),
  updated_at timestamptz not null default now()
);
alter table v3.concept_images enable row level security;
revoke all on table v3.concept_images from public, anon, authenticated;
grant select, insert, update on table v3.concept_images to service_role;

create function v3.flashcard_review_context(p_user_id uuid, p_concept_id uuid)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'eligible', coalesce(bool_or(sc.status in ('active', 'backlog')), false)
      and not exists (select 1 from v3.learner_known_concepts k
                      where k.user_id = p_user_id and k.concept_id = p_concept_id),
    'review_state', (select to_jsonb(r) from v3.review_states r
                     where r.user_id = p_user_id and r.concept_id = p_concept_id
                       and r.review_mode = 'concept_to_meaning'))
  from v3.saved_concepts sc
  where sc.user_id = p_user_id and sc.concept_id = p_concept_id;
$$;

-- ReviewState and ReviewEvent commit together; a stale version reports a conflict and is recomputed.
create function v3.commit_flashcard_review(p_user_id uuid, p_concept_id uuid, p_transition jsonb)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  r v3.review_states%rowtype;
  previous jsonb := p_transition->'previous';
  target jsonb := p_transition->'next';
  event jsonb := p_transition->'event';
  reviewed timestamptz := (event->>'reviewed_at')::timestamptz;
begin
  perform 1 from v3.saved_concepts sc where sc.user_id = p_user_id and sc.concept_id = p_concept_id
    and sc.status in ('active', 'backlog') for update;
  if not found or exists (select 1 from v3.learner_known_concepts k
                          where k.user_id = p_user_id and k.concept_id = p_concept_id) then
    return 'skipped';
  end if;
  if (previous->>'user_id')::uuid is distinct from p_user_id
     or (target->>'user_id')::uuid is distinct from p_user_id
     or (previous->>'concept_id')::uuid is distinct from p_concept_id
     or (target->>'concept_id')::uuid is distinct from p_concept_id
     or previous->>'review_mode' is distinct from 'concept_to_meaning'
     or target->>'review_mode' is distinct from 'concept_to_meaning'
     or event->>'review_mode' is distinct from 'concept_to_meaning'
     or event->>'provenance' is distinct from 'flashcard_memory'
     or (event->>'rating')::integer not in (1, 2, 3)
     or (target->>'last_reviewed_at')::timestamptz is distinct from reviewed
     or target->>'review_state_id' is distinct from previous->>'review_state_id'
     or event->>'review_state_id' is distinct from previous->>'review_state_id'
     or (target->>'version')::integer is distinct from (previous->>'version')::integer + 1 then
    raise exception 'invalid_flashcard_review_transition';
  end if;
  select * into r from v3.review_states where user_id = p_user_id and concept_id = p_concept_id
    and review_mode = 'concept_to_meaning' for update;
  if not found then
    if p_transition->>'create' is distinct from 'true' or (previous->>'version')::integer <> 0 then
      return 'conflict';
    end if;
    insert into v3.review_states(id, user_id, concept_id, review_mode, fsrs_state, due_at, version)
      values ((previous->>'review_state_id')::uuid, p_user_id, p_concept_id, 'concept_to_meaning', 'new', reviewed, 0)
      on conflict (user_id, concept_id, review_mode) do nothing returning * into r;
    if not found then return 'conflict'; end if;
  elsif p_transition->>'create' is distinct from 'false' then
    return 'conflict';
  end if;
  if r.id is distinct from (previous->>'review_state_id')::uuid
     or r.version is distinct from (previous->>'version')::integer then
    return 'conflict';
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
    values (r.id, 'concept_to_meaning', (event->>'rating')::integer, 'flashcard_memory',
            event->'previous_scheduling_state', event->'resulting_scheduling_state', reviewed);
  return 'applied';
end;
$$;

revoke all on function v3.flashcard_review_context(uuid, uuid) from public, anon, authenticated;
revoke all on function v3.commit_flashcard_review(uuid, uuid, jsonb) from public, anon, authenticated;
grant execute on function v3.flashcard_review_context(uuid, uuid) to service_role;
grant execute on function v3.commit_flashcard_review(uuid, uuid, jsonb) to service_role;
