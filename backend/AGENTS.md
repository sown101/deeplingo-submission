# Backend

Inherits the root [rules](../AGENTS.md). Former backend rules are archived in
`../docs/archive/legacy-rules/backend-AGENTS.md` (evidence, not authority).

## Commands

Run from `backend/` with the project virtualenv (`venv/`) active.

- All tests: `python -m pytest -q` (`pytest.ini` points at `tests/`).
- Boundary checks: `python -m pytest -q tests/architecture` (import-linter contracts in
  `.importlinter`). Keep green.
- Worker: `celery -A app.bootstrap.worker`.
- Migrations: `supabase/migrations/`. Never edit a migration that was already applied. Applying
  one to any environment needs the owner's approval for that environment.

## Cautions

- Do not log secrets, learner responses or raw provider error bodies.
