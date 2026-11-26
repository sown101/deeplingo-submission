-- B1: remove the AI cost ledger (owner-approved plan of 2026-10-26). Forward-only.
--
-- The ledger (v3.ai_budget_scopes, v3.ai_cost_calls and the budget functions and view) was off by default
-- (AI_COST_LEDGER_MODE=off) and is no longer read or written by the application. The live per-learner limit on new
-- video imports (v3.learner_new_video_imports, v3.charge_new_video_import) is NOT touched.
-- The failure codes budget_exhausted and budget_unavailable stay allowed by v3.video_work_intents' check constraint.
--
-- Order: apply 20261027110000_graded_attempt_b4_2 first, deploy the application, then this file (file order = apply
-- order). Not applied to any environment by this file's author; applying it needs the owner's approval.
-- Every statement is `if exists`, so the file is a no-op where the ledger was never applied.

drop view if exists v3.ai_cost_call_charges;

drop function if exists v3.reserve_ai_budget(uuid, uuid, text, text, text, text, numeric, integer, uuid);
-- M2.3b replaces the 8-argument form; it is still there where only M2.3a was applied.
drop function if exists v3.reserve_ai_budget(uuid, uuid, text, text, text, text, numeric, integer);
drop function if exists v3.settle_ai_budget(uuid, numeric, integer, bigint, bigint, bigint);
drop function if exists v3.release_ai_budget(uuid);
drop function if exists v3.expire_ai_budget(integer);
drop function if exists v3.ensure_ai_budget_scope(text, uuid, numeric);

drop table if exists v3.ai_cost_calls;
drop table if exists v3.ai_budget_scopes;
