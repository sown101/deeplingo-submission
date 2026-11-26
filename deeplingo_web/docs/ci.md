# Web CI & Release Quality Gates

Status: implemented (WEB-8A). Provider: **GitHub Actions** (the repository
is hosted on GitHub; no other CI system existed).

## Local verification

Canonical commands (CI invokes exactly these package scripts — compiler and
test configuration live only in the repository, never in CI YAML):

```text
npm run typecheck            # strict TypeScript (tsc -b)
npm run lint                 # W07 hooks/static-quality gate (rules-of-hooks blocking)
npm test                     # unit + component tests (Vitest, jsdom)
npm run build                # typecheck + production Vite build
npm run audit:build          # dist exposure audit (secrets/maps/env)
npm run check:bundle         # bundle budget: initial JS gzip ≤ 115 KiB
npm run test:e2e:deterministic   # deterministic browser specs (Playwright, mocked backend)
npm run measure:bundle       # local: per-asset raw/gzip + initial-entry table
```

Node runtime: **>= 22** (`engines` in `deeplingo_web/package.json`); CI uses
Node 24 with the existing `package-lock.json` (`npm ci`).

## CI classification

| Workflow | Jobs | Trigger | Classification | Secrets |
| --- | --- | --- | --- | --- |
| `.github/workflows/web-quality.yml` | `quality` (install → typecheck → lint → test → build → exposure audit → bundle budget) | push/PR touching `deeplingo_web/**` | **PR-required** (mandatory, no `continue-on-error`) | none |
| `.github/workflows/web-quality.yml` | `browser-e2e` (deterministic, mocked) | same as above | **PR-required** | none |
| `.github/workflows/web-product-e2e.yml` | `product-e2e` (real backend, real auth) | **manual** (`workflow_dispatch`) or **release-gated** (`workflow_call`) | external-integration proof — **not** PR-required | server-side only (see below) |

## Deterministic browser gate (Category A)

`e2e/deterministic/app.spec.ts` (Playwright, Chromium) proves real rendering,
routing and guards with **zero external systems**:

- every `/api/v1/v3/**` request is answered from local fixtures mirroring the
  learner-safe DTO contracts;
- every non-dev-server request (Supabase, YouTube, …) is **aborted** — the
  specs fail if any external network is contacted;
- the Supabase session is seeded into `localStorage`, so no auth network call
  occurs;
- the app receives only dummy browser-safe env values
  (`VITE_API_BASE_URL=/api/v1/v3`, dummy Supabase URL/publishable key).
- asserts the seeded JWT is attached to learner API calls, that protected
  routes redirect when unauthenticated, that only `sample_count > 0` skills
  render, and that no authority fields (`concept_id`, `sense_key`, mastery)
  appear in the Concept UI.

## Full Product E2E (Category B — external integration)

`scripts/e2e_product_v1.mjs` exercises the real
journey. These are **honestly classified as non-deterministic** because they
require:

- a reachable FastAPI development backend (`uvicorn app.main:app`);
- hosted development Supabase (real Auth + database);
- YouTube reachability (video playback/processing);
- the external LLM provider for review-origin generated activities (review
  CLOZE/MCQ materialization) — known intermittent free-router availability.

Failure semantics: any step `FAIL` **or `PARTIAL`** exits non-zero; a
server-side Review `materialization_failed` fails the happy-path proof
explicitly; review availability waits are condition-based with bounded
polling, not arbitrary long sleeps.

Cleanup: the runners dispose the disposable learner via the guarded
`scripts/e2e_learner.py cleanup` (requires `ALLOW_TEST_SEEDING=true` and an
exact `SMOKE_EXPECTED_SUPABASE_PROJECT_REF` match, refuses production) in a
`finally` block on success **and** failure; cleanup failure fails the gate.
Cleanup deletes only the disposable learner's rows — shared/global content
(videos, concepts, learning objects) is never touched. No learner authority
is seeded manually; no caller-controlled user ID is sent to V3 learner APIs.

`DEEPLINGO_E2E_KEEP_LEARNER=1` may be used for local debugging only; CI never
sets it.

## Environment and secret boundary

| Variable | Browser (`VITE_*`) | Server-side CI process | Notes |
| --- | --- | --- | --- |
| `VITE_API_BASE_URL` | yes | n/a | `/api/v1/v3` or absolute URL |
| `VITE_SUPABASE_URL` | yes (publishable project URL) | n/a | |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | yes | n/a | anon/publishable key only |
| `SUPABASE_URL`, `SUPABASE_KEY` | never | Product E2E job (uvicorn, learner helper) | passed as OS env, GitHub masks values |
| `SUPABASE_SERVICE_ROLE_KEY` | **never** | Product E2E job only | never exported as `VITE_*` |
| `AI_*` provider config | never | Product E2E job (uvicorn) | never printed; GitHub masking |
| `REDIS_URL`, DB passwords | never | never introduced in Web CI | |

Logs redact credentials: the runners and helpers print only step results,
status JSON, and state-file **paths** — never tokens, passwords, or keys.
