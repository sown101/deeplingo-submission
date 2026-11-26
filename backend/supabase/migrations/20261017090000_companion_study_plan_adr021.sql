-- ADR-021 G1: the learner's daily study plan and its proposals.
--
-- A plan is a snapshot the server composes the first time a learner opens the app on a day:
-- up to a few proposals (review, a conversation, video practice, saved words, add a video), each
-- with a short reason in the support language. Proposals point at existing resources; accepting
-- one only records the learner's choice, and the client then opens that resource through its own
-- endpoint, which rechecks ownership and policy. Nothing here is learner state: no grading,
-- mastery, review or progression reads or writes these tables.
--
-- Learners read their own rows; every write goes through authenticated FastAPI routes that
-- derive CurrentUser.id (service role). Forward-only.

create table if not exists v3.companion_plans (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  plan_day date not null,
  intro text not null,
  text_source text not null,
  model text,
  prompt_version text,
  created_at timestamptz not null default now(),
  constraint companion_plans_one_per_day unique (user_id, language_code, plan_day),
  constraint companion_plans_intro_check check (char_length(intro) between 1 and 300),
  constraint companion_plans_text_source_check check (text_source in ('model', 'template')),
  constraint companion_plans_model_check check ((text_source = 'model') = (model is not null))
);

comment on table v3.companion_plans is
  'ADR-021 G1: one daily study-plan snapshot per learner, language and day. Server-written; '
  'learners read their own rows. Not learner state.';

create table if not exists v3.companion_proposals (
  id uuid primary key default gen_random_uuid(),
  plan_id uuid not null references v3.companion_plans(id) on delete cascade,
  user_id uuid not null references v3.profiles(id) on delete cascade,
  position smallint not null,
  kind text not null,
  library_item_id uuid references v3.learner_videos(id) on delete cascade,
  video_title text,
  companion_entry text,
  item_count integer,
  minutes smallint not null,
  reason text not null,
  status text not null default 'open',
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  constraint companion_proposals_position_unique unique (plan_id, position),
  constraint companion_proposals_position_check check (position between 0 and 9),
  constraint companion_proposals_kind_check check (
    kind in ('review', 'conversation', 'video_practice', 'my_words', 'add_video')),
  constraint companion_proposals_entry_check check (
    (kind = 'conversation') = (companion_entry is not null)
    and (companion_entry is null or companion_entry in ('video', 'review', 'home'))),
  constraint companion_proposals_video_check check (
    (kind = 'video_practice' or coalesce(companion_entry, '') = 'video') = (library_item_id is not null)),
  constraint companion_proposals_title_check check (
    video_title is null or char_length(video_title) between 1 and 300),
  constraint companion_proposals_count_check check (item_count is null or item_count >= 0),
  constraint companion_proposals_minutes_check check (minutes between 1 and 60),
  constraint companion_proposals_reason_check check (char_length(reason) between 1 and 300),
  constraint companion_proposals_status_check check (status in ('open', 'accepted', 'dismissed')),
  constraint companion_proposals_decided_check check ((status = 'open') = (decided_at is null))
);

comment on table v3.companion_proposals is
  'ADR-021 G1: proposals of a daily study plan. The learner accepts or dismisses them; accepting '
  'opens an existing resource through its own endpoint. Not learner state.';

create index if not exists companion_proposals_plan_idx on v3.companion_proposals (plan_id, position);
create index if not exists companion_proposals_user_idx on v3.companion_proposals (user_id);
create index if not exists companion_proposals_library_item_idx
  on v3.companion_proposals (library_item_id) where library_item_id is not null;

alter table v3.companion_plans enable row level security;
alter table v3.companion_proposals enable row level security;

revoke all privileges on v3.companion_plans from anon, authenticated;
revoke all privileges on v3.companion_proposals from anon, authenticated;
grant select on v3.companion_plans to authenticated;
grant select on v3.companion_proposals to authenticated;
grant all privileges on v3.companion_plans to service_role;
grant all privileges on v3.companion_proposals to service_role;

drop policy if exists "Users can read own companion plans" on v3.companion_plans;
create policy "Users can read own companion plans"
  on v3.companion_plans for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own companion proposals" on v3.companion_proposals;
create policy "Users can read own companion proposals"
  on v3.companion_proposals for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- Creates the day's plan and its proposals in one transaction, or returns the plan that a
-- concurrent request already created. Proposals are trusted server values; the caller has
-- already checked that every library item belongs to the learner.
create or replace function v3.create_companion_plan(
  p_user_id uuid,
  p_language_code text,
  p_plan_day date,
  p_intro text,
  p_text_source text,
  p_model text,
  p_prompt_version text,
  p_items jsonb
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_plan_id uuid;
  v_item jsonb;
  v_position integer := 0;
begin
  if p_items is null or jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) > 10 then
    raise exception 'companion_plan_conflict: invalid_items';
  end if;

  insert into v3.companion_plans (user_id, language_code, plan_day, intro, text_source, model, prompt_version)
  values (p_user_id, p_language_code, p_plan_day, p_intro, p_text_source, p_model, p_prompt_version)
  on conflict (user_id, language_code, plan_day) do nothing
  returning id into v_plan_id;

  if v_plan_id is null then
    select id into v_plan_id from v3.companion_plans
    where user_id = p_user_id and language_code = p_language_code and plan_day = p_plan_day;
    return v_plan_id;
  end if;

  for v_item in select value from jsonb_array_elements(p_items) loop
    insert into v3.companion_proposals (
      plan_id, user_id, position, kind, library_item_id, video_title, companion_entry, item_count,
      minutes, reason)
    values (
      v_plan_id, p_user_id, v_position, v_item->>'kind', nullif(v_item->>'library_item_id', '')::uuid,
      v_item->>'video_title', v_item->>'companion_entry', (v_item->>'item_count')::integer,
      (v_item->>'minutes')::smallint, v_item->>'reason');
    v_position := v_position + 1;
  end loop;
  return v_plan_id;
end;
$$;

revoke all on function v3.create_companion_plan(uuid, text, date, text, text, text, text, jsonb)
  from public, anon, authenticated;
grant execute on function v3.create_companion_plan(uuid, text, date, text, text, text, text, jsonb)
  to service_role;
