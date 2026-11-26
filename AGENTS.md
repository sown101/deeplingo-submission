# DeepLingo agent rules

DeepLingo is a language-learning product: learners study from real content such as videos,
guided by a companion. The code is `backend/` (FastAPI, PostgreSQL/Supabase, Celery),
and `deeplingo_web/` (React/TypeScript); these facts come from the code, not from legacy docs.

The owner is redesigning the project: learning method, architecture, domain model, data and
component rules are not yet re-decided. Everything written before the redesign is **legacy**:
the old ADRs, architecture docs and product plans were deleted and stay in git history
(commit `2b67a0a`); the former AGENTS.md files are in `docs/archive/legacy-rules/`. Legacy
records what was tried and why. It is evidence, not authority.

## Whose instruction wins

1. Platform safety, then the owner's current instruction in chat.
2. These rules.
3. Legacy documents: never cite one as proof that something is correct. If a task depends on a
   legacy decision, name it and ask the owner whether it still holds.

A task may propose a change to these rules but must not silently override them. When a task
conflicts with a rule, state the conflict and ask.

## Safety

- Do not change any live, shared or paid environment (database migrations, grants, deploys, AI
  or provider calls beyond a stated budget) without the owner's explicit approval for that
  action in this session. Name the environment first.
- Never print, log or commit secrets, tokens, service-role keys or learner data. Never put them
  in client code or `VITE_` values.
- Do not delete, move or overwrite files you did not create, and do not run `git reset --hard`,
  `git clean`, `git checkout -- <path>` or a forced push, without approval. Commit or push only
  when asked.
- Preserve uncommitted work by other people or agents.
- Existing automated checks (tests, import-linter, `tests/architecture`) stay green. Do not
  weaken, skip or delete one to make a change pass; changing one needs the owner's approval and
  a stated reason.
- Do not delete shared or global content when cleaning up learner test data.

## How to work

- Before editing a file, read it and the tests that cover it. For a trivial change (a typo, a
  one-line fix) use judgment and keep the process short.
- When a request can be read more than one way, state the reading you chose or ask; do not
  pick one silently.
- Change only the files and lines the task needs. Keep the surrounding code's naming,
  formatting and structure. Put unrelated problems in your report instead of fixing them.
- Write the minimum that solves the task: no speculative features, abstractions or
  configuration. Remove only code that your own change made unused; mention other dead code.
- Before a change that touches more than one file, a schema, or an external service, write in
  the reply the assumption you rely on and the command or observation that will show it worked.
- Ask the owner when the decision is theirs: product direction, learning method, architecture.
- Done means the check you named ran and passed. For a bug, add a test that fails before the
  fix and passes after it.
- Normal tests must not need live AI credentials or quota.
- Commit messages follow `type(scope): subject`, as in `git log`.
- Only `main` is the trunk: one branch per task from `origin/main`, a PR into `main`, delete the
  branch after merge.

## Reporting to the owner

- Write to the owner in Vietnamese unless asked otherwise.
- Report in this order: what works and how it was verified (command and result); what was not
  verified; what is blocked or risky; the next step.
- Use these terms exactly and never blur them: **code written**, **tested locally**,
  **verified in a real environment**.
- Never claim a check passed unless you ran it in this session. Do not present a historical
  result as a new one. Report an unknown outcome (timeout, partial write) as unknown.

## Documents

- One place per fact. Progress belongs in one status file, `docs/product/STATUS.md`.
- What the product is, its requirements and the owner's decisions are in `docs/product/PRD.md`.
  Read it before a task that changes product behaviour and update it in the same PR. An item
  labelled "Đề xuất" or "Cần chốt" is not a decision: ask the owner.
- Do not create per-round or per-task documents. Put evidence of a round in the commit message
  or PR description.
- Create a new `.md` file only when the task asks for it; otherwise update the existing one.

## Components

`backend/` and `deeplingo_web/` each have a short AGENTS.md with commands.
The Flutter app (`deeplingo_app/`) was removed; it lives in git history at tag `archive/flutter-app-20261115`.
The older `mobile_app/` client was removed earlier; it stays in git history too.
