-- M2.3a DRAFT — NOT APPLIED ANYWHERE. Applying it needs separate owner approval and a rollback check on
-- development first (as for A26). Design: docs/product/M2_3_COST_CAPS_DESIGN.md sections 5 and 6.
--
-- A per-call AI cost ledger with budget scopes. Nothing calls it yet: no transport, no enforcement. The study
-- session (section 3 of the design) is not part of this slice; scope kinds are region and video preparation.
--
-- Rules every function keeps:
-- - Every call row has a client-generated id; every RPC is idempotent by that id. Reusing an id for a different
--   request is refused (DL102), never silently accepted.
-- - States move one way: reserved -> settled | released | expired. A scope's spend is the sum of its rows, so a
--   call is never charged twice.
-- - Lock order is always scope row, then call rows (no deadlock between reserve, settle, release and expiry).
-- - No private helper functions: under SECURITY INVOKER every function a caller reaches needs its own grant, so
--   the expiry update is written out where it is needed and every defined function is granted to service_role.
-- - A reservation past its expiry is charged in full (unknown outcome is never zero). A settle that arrives after
--   expiry is kept for reporting only (late_actual_usd).
-- - A settled cost above its reservation sets bound_violation and locks the scope (DL103 on later reserves).
-- - Amounts must be finite and positive; NaN and infinity are refused.

create table if not exists v3.ai_budget_scopes (
  id uuid primary key default extensions.gen_random_uuid(),
  kind text not null check (kind in ('region_preparation', 'video_preparation')),
  scope_key uuid not null,
  cap_usd numeric(14, 8) not null check (cap_usd > 0 and cap_usd < 1000),
  locked_at timestamptz,
  lock_reason text,
  created_at timestamptz not null default now(),
  constraint ai_budget_scopes_key unique (kind, scope_key)
);

create table if not exists v3.ai_cost_calls (
  id uuid primary key,
  scope_id uuid references v3.ai_budget_scopes(id) on delete restrict,
  kind text not null check (btrim(kind) <> ''),
  provider text not null check (btrim(provider) <> ''),
  model text not null check (btrim(model) <> ''),
  price_version text not null check (btrim(price_version) <> ''),
  requested_at timestamptz not null default clock_timestamp(),
  reserved_usd numeric(14, 8) not null check (reserved_usd > 0 and reserved_usd < 1000),
  expires_at timestamptz not null,
  state text not null default 'reserved' check (state in ('reserved', 'settled', 'released', 'expired')),
  closed_at timestamptz,
  http_status integer,
  prompt_tokens bigint check (prompt_tokens >= 0),
  output_tokens bigint check (output_tokens >= 0),
  total_tokens bigint check (total_tokens >= 0),
  actual_usd numeric(14, 8) check (actual_usd >= 0),
  charged_usd numeric(14, 8) not null default 0 check (charged_usd >= 0),
  late_actual_usd numeric(14, 8) check (late_actual_usd >= 0),
  bound_violation boolean not null default false,
  settle_conflict boolean not null default false,
  constraint ai_cost_calls_state_chk check (
    (state = 'reserved' and closed_at is null and charged_usd = 0)
    or (state = 'released' and closed_at is not null and charged_usd = 0)
    or (state = 'settled' and closed_at is not null)
    or (state = 'expired' and closed_at is not null and charged_usd = reserved_usd)
  )
);

create index if not exists ai_cost_calls_open_idx on v3.ai_cost_calls (scope_id, expires_at) where state = 'reserved';
create index if not exists ai_cost_calls_requested_at_idx on v3.ai_cost_calls (requested_at);

alter table v3.ai_budget_scopes enable row level security;
alter table v3.ai_cost_calls enable row level security;
revoke all privileges on v3.ai_budget_scopes, v3.ai_cost_calls from public, anon, authenticated;
grant all privileges on v3.ai_budget_scopes, v3.ai_cost_calls to service_role;

-- A scope is created once; concurrent creators get the same row and the first cap.
create or replace function v3.ensure_ai_budget_scope(p_kind text, p_scope_key uuid, p_cap_usd numeric)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare s v3.ai_budget_scopes%rowtype;
begin
  if p_kind is null or p_scope_key is null or p_cap_usd is null
     or not (p_cap_usd > 0 and p_cap_usd < 1000) then
    raise exception 'Invalid AI budget scope' using errcode = '22023';
  end if;
  insert into v3.ai_budget_scopes (kind, scope_key, cap_usd) values (p_kind, p_scope_key, p_cap_usd)
    on conflict (kind, scope_key) do nothing;
  select * into s from v3.ai_budget_scopes where kind = p_kind and scope_key = p_scope_key;
  return to_jsonb(s);
end $$;

create or replace function v3.reserve_ai_budget(
  p_id uuid, p_scope_id uuid, p_kind text, p_provider text, p_model text, p_price_version text,
  p_amount_usd numeric, p_ttl_seconds integer
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare s v3.ai_budget_scopes%rowtype; c v3.ai_cost_calls%rowtype; used numeric;
begin
  if p_id is null or coalesce(btrim(p_kind), '') = '' or coalesce(btrim(p_provider), '') = ''
     or coalesce(btrim(p_model), '') = '' or coalesce(btrim(p_price_version), '') = ''
     or p_amount_usd is null or not (p_amount_usd > 0 and p_amount_usd < 1000)
     or p_ttl_seconds is null or p_ttl_seconds < 1 or p_ttl_seconds > 86400 then
    raise exception 'Invalid AI cost reservation' using errcode = '22023';
  end if;
  if p_scope_id is not null then
    -- Lock order: scope first. Concurrent reserves of one scope (or one id) are serialized here.
    select * into s from v3.ai_budget_scopes where id = p_scope_id for update;
    if not found or s.kind <> p_kind then
      raise exception 'Unknown AI budget scope' using errcode = '22023';
    end if;
  end if;
  -- Idempotency is answered BEFORE any budget check: a retried reservation is never refused as exhausted.
  -- A replay past its expiry is answered as expired (charged in full), never confirmed as reserved.
  select * into c from v3.ai_cost_calls where id = p_id for update;
  if found then
    if c.scope_id is distinct from p_scope_id or c.kind <> p_kind or c.provider <> p_provider
       or c.model <> p_model or c.price_version <> p_price_version or c.reserved_usd <> p_amount_usd then
      raise exception 'AI cost call id reused for another request' using errcode = 'DL102';
    end if;
    if c.state = 'reserved' and c.expires_at <= clock_timestamp() then
      update v3.ai_cost_calls set state = 'expired', charged_usd = reserved_usd, closed_at = clock_timestamp()
      where id = c.id returning * into c;
    end if;
    return to_jsonb(c);
  end if;
  if p_scope_id is not null then
    if s.locked_at is not null then
      raise exception 'AI budget scope is locked' using errcode = 'DL103';
    end if;
    -- Overdue reservations are charged in full before the sum.
    update v3.ai_cost_calls set state = 'expired', charged_usd = reserved_usd, closed_at = clock_timestamp()
      where scope_id = s.id and state = 'reserved' and expires_at <= clock_timestamp();
    select coalesce(sum(charged_usd), 0) + coalesce(sum(reserved_usd) filter (where state = 'reserved'), 0)
      into used from v3.ai_cost_calls where scope_id = s.id;
    if used + p_amount_usd > s.cap_usd then
      raise exception 'AI budget exhausted' using errcode = 'DL101';
    end if;
  end if;
  insert into v3.ai_cost_calls (id, scope_id, kind, provider, model, price_version, reserved_usd, expires_at)
    values (p_id, p_scope_id, p_kind, p_provider, p_model, p_price_version, p_amount_usd,
            clock_timestamp() + make_interval(secs => p_ttl_seconds))
    on conflict (id) do nothing
    returning * into c;
  if not found then  -- an unscoped twin committed first; same rules as above
    select * into c from v3.ai_cost_calls where id = p_id for update;
    if c.scope_id is distinct from p_scope_id or c.kind <> p_kind or c.provider <> p_provider
       or c.model <> p_model or c.price_version <> p_price_version or c.reserved_usd <> p_amount_usd then
      raise exception 'AI cost call id reused for another request' using errcode = 'DL102';
    end if;
    if c.state = 'reserved' and c.expires_at <= clock_timestamp() then
      update v3.ai_cost_calls set state = 'expired', charged_usd = reserved_usd, closed_at = clock_timestamp()
      where id = c.id returning * into c;
    end if;
  end if;
  return to_jsonb(c);
end $$;

create or replace function v3.settle_ai_budget(
  p_id uuid, p_actual_usd numeric, p_http_status integer,
  p_prompt_tokens bigint, p_output_tokens bigint, p_total_tokens bigint
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare sid uuid; c v3.ai_cost_calls%rowtype; actual numeric;
begin
  select scope_id into sid from v3.ai_cost_calls where id = p_id;
  if sid is not null then
    perform 1 from v3.ai_budget_scopes where id = sid for update;  -- lock order: scope first
  end if;
  select * into c from v3.ai_cost_calls where id = p_id for update;
  if not found then
    raise exception 'Unknown AI cost call' using errcode = '22023';
  end if;
  -- An unknown or impossible cost is null: the reservation stays charged in full.
  actual := case when p_actual_usd is not null and p_actual_usd >= 0 and p_actual_usd < 1000
                 then p_actual_usd end;
  if c.state = 'reserved' and c.expires_at <= clock_timestamp() then
    update v3.ai_cost_calls set state = 'expired', charged_usd = reserved_usd, closed_at = clock_timestamp()
      where id = c.id returning * into c;
  end if;
  if c.state = 'reserved' then
    update v3.ai_cost_calls set state = 'settled', closed_at = clock_timestamp(), actual_usd = actual,
      charged_usd = coalesce(actual, reserved_usd), http_status = p_http_status,
      prompt_tokens = p_prompt_tokens, output_tokens = p_output_tokens, total_tokens = p_total_tokens,
      bound_violation = actual is not null and actual > reserved_usd
      where id = c.id returning * into c;
    if c.bound_violation and c.scope_id is not null then
      update v3.ai_budget_scopes set locked_at = clock_timestamp(), lock_reason = 'bound_violation'
        where id = c.scope_id and locked_at is null;
    end if;
  elsif c.state = 'settled' then
    if c.actual_usd is distinct from actual then  -- a repeat with another value keeps the first
      update v3.ai_cost_calls set settle_conflict = true where id = c.id returning * into c;
    end if;
  elsif c.state = 'expired' then
    -- The charge stays the reservation (never charged twice); a late cost above it still proves the bound wrong.
    if c.late_actual_usd is null and actual is not null then
      update v3.ai_cost_calls set late_actual_usd = actual,
        bound_violation = bound_violation or actual > reserved_usd,
        http_status = coalesce(http_status, p_http_status), prompt_tokens = coalesce(prompt_tokens, p_prompt_tokens),
        output_tokens = coalesce(output_tokens, p_output_tokens), total_tokens = coalesce(total_tokens, p_total_tokens)
        where id = c.id returning * into c;
      if c.bound_violation and c.scope_id is not null then
        update v3.ai_budget_scopes set locked_at = clock_timestamp(), lock_reason = 'bound_violation'
          where id = c.scope_id and locked_at is null;
      end if;
    elsif c.late_actual_usd is distinct from actual then
      update v3.ai_cost_calls set settle_conflict = true where id = c.id returning * into c;
    end if;
  else  -- released, then settled: the AI was sent after a release; record the breach, charge nothing more
    update v3.ai_cost_calls set settle_conflict = true where id = c.id returning * into c;
  end if;
  return to_jsonb(c);
end $$;

-- Release a reservation whose request was never sent. Unknown ids return null (the reserve never landed).
create or replace function v3.release_ai_budget(p_id uuid)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare sid uuid; c v3.ai_cost_calls%rowtype;
begin
  select scope_id into sid from v3.ai_cost_calls where id = p_id;
  if sid is not null then
    perform 1 from v3.ai_budget_scopes where id = sid for update;
  end if;
  select * into c from v3.ai_cost_calls where id = p_id for update;
  if not found then
    return null;
  end if;
  if c.state = 'reserved' and c.expires_at <= clock_timestamp() then
    update v3.ai_cost_calls set state = 'expired', charged_usd = reserved_usd, closed_at = clock_timestamp()
      where id = c.id returning * into c;
  elsif c.state = 'reserved' then
    update v3.ai_cost_calls set state = 'released', closed_at = clock_timestamp() where id = c.id returning * into c;
  end if;
  return to_jsonb(c);
end $$;

-- Periodic sweep: charge overdue reservations in full. Returns how many were expired.
create or replace function v3.expire_ai_budget(p_limit integer default 100)
returns integer language plpgsql security invoker set search_path = '' as $$
declare r record; c v3.ai_cost_calls%rowtype; n integer := 0;
begin
  if p_limit is null or p_limit < 1 or p_limit > 1000 then
    raise exception 'Invalid AI budget sweep limit' using errcode = '22023';
  end if;
  for r in select id, scope_id from v3.ai_cost_calls
           where state = 'reserved' and expires_at <= clock_timestamp() order by expires_at limit p_limit loop
    if r.scope_id is not null then
      perform 1 from v3.ai_budget_scopes where id = r.scope_id for update;
    end if;
    select * into c from v3.ai_cost_calls where id = r.id for update;
    if c.state = 'reserved' and c.expires_at <= clock_timestamp() then  -- not settled meanwhile
      update v3.ai_cost_calls set state = 'expired', charged_usd = reserved_usd, closed_at = clock_timestamp()
      where id = c.id returning * into c;
      n := n + 1;
    end if;
  end loop;
  return n;
end $$;

revoke all on function v3.ensure_ai_budget_scope(text, uuid, numeric) from public, anon, authenticated;
revoke all on function v3.reserve_ai_budget(uuid, uuid, text, text, text, text, numeric, integer) from public, anon, authenticated;
revoke all on function v3.settle_ai_budget(uuid, numeric, integer, bigint, bigint, bigint) from public, anon, authenticated;
revoke all on function v3.release_ai_budget(uuid) from public, anon, authenticated;
revoke all on function v3.expire_ai_budget(integer) from public, anon, authenticated;
grant execute on function v3.ensure_ai_budget_scope(text, uuid, numeric) to service_role;
grant execute on function v3.reserve_ai_budget(uuid, uuid, text, text, text, text, numeric, integer) to service_role;
grant execute on function v3.settle_ai_budget(uuid, numeric, integer, bigint, bigint, bigint) to service_role;
grant execute on function v3.release_ai_budget(uuid) to service_role;
grant execute on function v3.expire_ai_budget(integer) to service_role;
