-- M2.3b DRAFT — NOT APPLIED ANYWHERE. Depends on migration 20261021130000_ai_cost_ledger_m2_3a (apply that first).
-- Applying it needs separate owner approval and a rollback check on development first.
-- Design: docs/product/M2_3_COST_CAPS_DESIGN.md sections 4-6; runbook: docs/runbooks/ai-cost-ledger-pg-verification.md.
--
-- Adds two things the recording transport needs and nothing that caps:
-- 1. `work_key`: the region or video a call is spent on. Stored on the call, so the ledger alone answers
--    "what did this region cost". It is not a budget scope and never limits anything.
-- 2. `v3.ai_cost_call_charges`: the read rule for reporting. A reservation whose settle never landed stays `reserved`
--    in the table (nothing in the runtime transitions it); the view charges it in full once it is past expires_at, as
--    design section 5 says. Reports must read this view, not `charged_usd` of the table.

alter table v3.ai_cost_calls add column if not exists work_key uuid;
create index if not exists ai_cost_calls_work_key_idx on v3.ai_cost_calls (work_key) where work_key is not null;

-- The reserve signature gains p_work_key (defaulted, so existing named callers keep working). The old signature is
-- dropped first so PostgREST sees exactly one function.
drop function if exists v3.reserve_ai_budget(uuid, uuid, text, text, text, text, numeric, integer);

create or replace function v3.reserve_ai_budget(
  p_id uuid, p_scope_id uuid, p_kind text, p_provider text, p_model text, p_price_version text,
  p_amount_usd numeric, p_ttl_seconds integer, p_work_key uuid default null
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
       or c.model <> p_model or c.price_version <> p_price_version or c.reserved_usd <> p_amount_usd
       or c.work_key is distinct from p_work_key then
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
  insert into v3.ai_cost_calls (id, scope_id, kind, provider, model, price_version, reserved_usd, expires_at, work_key)
    values (p_id, p_scope_id, p_kind, p_provider, p_model, p_price_version, p_amount_usd,
            clock_timestamp() + make_interval(secs => p_ttl_seconds), p_work_key)
    on conflict (id) do nothing
    returning * into c;
  if not found then  -- an unscoped twin committed first; same rules as above
    select * into c from v3.ai_cost_calls where id = p_id for update;
    if c.scope_id is distinct from p_scope_id or c.kind <> p_kind or c.provider <> p_provider
       or c.model <> p_model or c.price_version <> p_price_version or c.reserved_usd <> p_amount_usd
       or c.work_key is distinct from p_work_key then
      raise exception 'AI cost call id reused for another request' using errcode = 'DL102';
    end if;
    if c.state = 'reserved' and c.expires_at <= clock_timestamp() then
      update v3.ai_cost_calls set state = 'expired', charged_usd = reserved_usd, closed_at = clock_timestamp()
      where id = c.id returning * into c;
    end if;
  end if;
  return to_jsonb(c);
end $$;

revoke all on function v3.reserve_ai_budget(uuid, uuid, text, text, text, text, numeric, integer, uuid)
  from public, anon, authenticated;
grant execute on function v3.reserve_ai_budget(uuid, uuid, text, text, text, text, numeric, integer, uuid)
  to service_role;

-- Reporting read rule (design section 5): a reservation past expires_at that was never settled is charged in full,
-- whether or not the sweep has run. `open` = reserved and not yet expired (in flight or unknown); it is charged as
-- nothing yet and reports must count it as unknown. Nothing in this view changes a row.
-- One as-of time per statement (statement_timestamp), and charged_usd is derived FROM charge_basis, so the two columns
-- of one row can never disagree, even exactly at expires_at.
create or replace view v3.ai_cost_call_charges with (security_invoker = true) as
select x.id, x.kind, x.work_key, x.scope_id, x.provider, x.model, x.price_version, x.requested_at, x.expires_at,
  x.charge_basis, x.reserved_usd, x.actual_usd, x.late_actual_usd, x.bound_violation,
  case when x.charge_basis = 'overdue_reserved' then x.reserved_usd else x.stored_charged_usd end as charged_usd
from (
  select c.id, c.kind, c.work_key, c.scope_id, c.provider, c.model, c.price_version, c.requested_at, c.expires_at,
    case when c.state = 'reserved' and c.expires_at <= statement_timestamp() then 'overdue_reserved'
         when c.state = 'reserved' then 'open'
         else c.state end as charge_basis,
    c.reserved_usd, c.actual_usd, c.late_actual_usd, c.bound_violation, c.charged_usd as stored_charged_usd
  from v3.ai_cost_calls c
) x;

revoke all on v3.ai_cost_call_charges from public, anon, authenticated;
grant select on v3.ai_cost_call_charges to service_role;

notify pgrst, 'reload schema';
