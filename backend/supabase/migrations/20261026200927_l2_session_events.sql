-- L2: durable derived evidence only. Raw text belongs to a separate volatile Redis (15 minutes).
-- Forward-only. Applying requires the owner's environment-specific approval.

create table v3.speaking_sessions (
  id uuid primary key,
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null check (language_code in ('en', 'zh')),
  library_item_id uuid references v3.learner_videos(id) on delete set null,
  context_key text not null check (length(context_key) between 1 and 150),
  targets jsonb not null check (jsonb_typeof(targets) = 'array' and jsonb_array_length(targets) between 1 and 12),
  status text not null default 'queued' check (status in ('queued', 'processing', 'projecting', 'completed', 'failed', 'expired')),
  events jsonb not null default '[]'::jsonb check (jsonb_typeof(events) = 'array' and jsonb_array_length(events) <= 12),
  error_code text check (error_code in ('analysis_unavailable', 'analysis_failed', 'expired')),
  occurred_at timestamptz not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  check (expires_at > occurred_at and expires_at <= occurred_at + interval '15 minutes')
);
create index speaking_sessions_user_idx on v3.speaking_sessions(user_id, occurred_at desc);
alter table v3.speaking_sessions enable row level security;
revoke all on v3.speaking_sessions from public, anon, authenticated;
grant select on v3.speaking_sessions to authenticated;
grant all on v3.speaking_sessions to service_role;
create policy "Learners read own speaking sessions" on v3.speaking_sessions
  for select to authenticated using ((select auth.uid()) = user_id);

-- One transaction commits the session result and append-only word-use evidence. No quotes are stored.
create function v3.complete_speaking_session(p_session_id uuid, p_uses jsonb, p_model text)
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
        and sc.status in ('active', 'backlog') and c.language_code = s.language_code
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
