-- M1 acceptance run: admit the scope kind 'acceptance_run' (design docs/review/m1-acceptance-run-design-v2-20261024.md).
--
-- Forward-only. No earlier migration is edited. Changes exactly one thing: the allowed values of
-- v3.ai_budget_scopes.kind gain 'acceptance_run'. No table, column, RPC, grant, RLS policy or trigger is touched.
-- The ledger RPCs accept any non-empty kind text on v3.ai_cost_calls, so they need no change, and the
-- reserve_ai_budget RPC already compares the call's kind with its scope's kind.
--
-- Applying it is an owner decision for an environment (never applied by a test or by a deploy step on its own).
-- Before applying, the constraint name is checked: a database with a different name stops here and changes nothing.

begin;

do $$
begin
  if not exists (
    select 1
      from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
     where n.nspname = 'v3'
       and t.relname = 'ai_budget_scopes'
       and c.conname = 'ai_budget_scopes_kind_check'
       and c.contype = 'c'
  ) then
    raise exception 'v3.ai_budget_scopes.ai_budget_scopes_kind_check not found; nothing was changed';
  end if;
end
$$;

alter table v3.ai_budget_scopes drop constraint ai_budget_scopes_kind_check;

alter table v3.ai_budget_scopes
  add constraint ai_budget_scopes_kind_check
  check (kind in ('region_preparation', 'video_preparation', 'acceptance_run'));

commit;
