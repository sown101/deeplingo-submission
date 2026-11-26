> **LEGACY — archived 2026-10-25.** Rules written before the project was redesigned. They record past hypotheses, not settled truth. Relative links below no longer resolve from this folder.

# Backend engineering rules

Inherit [root governance](../AGENTS.md). Canonical rules are in
[backend boundaries](../docs/architecture/BACKEND_BOUNDARIES.md) and
[data authority](../docs/architecture/DATA_AUTHORITY.md); open items in the
[debt register](../docs/architecture/DEBT_REGISTER.md).

## Business ownership

- identity: CurrentUser, verified identity and authorization primitives.
- content: reference content, semantic Concepts, occurrences, Library and preparation.
- learning: planner, sessions, activities, generation/validation/execution/progression.
- assessment: Attempts, grading, Evidence policy and AssessmentApplication coordination.
- learner: language profile/preferences, ConceptMastery, skill mapping/aggregation.
- review: due selection, context/mapping/provenance, scheduling, events and FSRSAdapter.
- bootstrap: configuration and concrete wiring, not business policy.

Package structure follows [ADR-015](../docs/architecture/adr/015-backend-module-structure.md):
`app/modules/<module>/{contracts.py,domain,application,infrastructure,api,worker}`,
technical capabilities in `app/platform/`, composition only in `app/bootstrap/`.
Boundaries are enforced by `.importlinter` (run in `tests/architecture/test_import_boundaries.py`);
a broken contract is a failing test, not documentation debt.
New code goes into the owning module; cross-module values come from the
other module's `contracts.py`, cross-module behavior through your own
`application/ports.py` Protocol wired in `bootstrap/wiring/`. Values follow the
module DAG `identity`/`kernel` -> `content` -> `learner` -> `assessment` -> `learning`
-> `review`; a back-edge is a `TYPE_CHECKING` annotation or a port, never a runtime
import. Moves are hard cuts with every importer, test and script rewritten; do not
add compatibility shims. Run the Celery worker with `celery -A app.bootstrap.worker`.

## Dependencies

API translates HTTP/DTOs into application commands and safe responses.
Application uses domain values/rules and abstract ports.
Infrastructure implements persistence, JWT verification, source, job and AI ports.
Domain does not import FastAPI, settings, repositories, vendor SDKs or transport DTOs.
FSRSAdapter is vendor-facing review infrastructure (`modules/review/infrastructure`), injected via a port.
Cross-module reads use the consumer's own `application/ports.py` Protocols, wired in bootstrap; other modules are imported only via `contracts.py`.
Assessment coordinates learner/review proposals through ports and one atomic commit.
Keep Evidence acceptance in assessment; target-value computation in learner/review.
No event bus is required for synchronous critical learner effects.

## Authentication and exposure

Derive learner identity from verified CurrentUser; recheck owner-scoped resource chains.
Service-role persistence makes route/service authorization mandatory despite RLS.
Do not copy legacy query-user-id or fallback-test-user patterns.
Content mutation requires trusted ingestor authorization or an authorized worker.
Never use editable user_metadata as a privileged role.
Document auth-mode capability differences; auth-server currently drops app_metadata.
Do not reintroduce retired legacy/proof routes or promote internal proof DTOs to client authority.
6B-1C retires the older numbered V3 Attempt upsert path; never restore it.

## Persistence

SQL migrations define durable schema, constraints, grants and transactional contracts.
Repositories implement data access; no grading, skill mapping or FSRS in SQL.
Preserve one authoritative Assessment per Attempt and one application per Assessment.
Mastery/skills/ReviewState/Event/application effects commit together with version checks.
Retry conflicts by reloading/recomputing with bounded attempts.
Never replace atomic RPCs with a sequence of REST writes during boundary extraction.
Keep LLM/source calls outside transactions; revalidate snapshots before commit.
Distinguish a successful write, a failed write and an unknown-outcome write.
Attempt submission requires a durable UUID and exact original raw response. Only retry/reconcile that original keyed POST; never regenerate a key after an unknown outcome. The service-only invoker RPC is the sole writer ([ADR-009](../docs/architecture/adr/009-immutable-attempt-submission.md)); it is qualified only on the development project.
Keep global content separate from learner-owned associations and cleanup.
New migrations are forward-only; baseline/history repair needs an explicit plan.
No live migration, grant change or destructive smoke without environment authorization.

## AI integration

Use LLMProvider, strict structured contracts and consuming-module prompt versions.
Select provider/model/base URL/key only in backend configuration/composition.
Keep extra fields forbidden, bounded score/confidence, existing verdict enum,
confidence threshold, trusted source grounding, leakage and injection defenses.
No prose scraping, silent fallback or threshold changes to accommodate a provider.
Provider output cannot author learner identity, mastery, skills, FSRS or completion.
OpenCode is unsupported as a runtime provider; free models are development-only.
Qualify each production workload/model separately; configuration eligibility is not proof.

## Jobs and reliability

Content owns ingestion/preparation task intent; Celery/Redis are infrastructure.
PostgreSQL owns persistent status; task return values are not product truth.
Use durable IDs, conditional claims, bounded retries and safe failure categories.
Durable intents, leases, bounded retries and the Linux prefork topology (ADR-010..013,
[async reliability](../docs/architecture/ASYNC_RELIABILITY.md)) are development-qualified only.
Do not claim exactly-once delivery or add distributed module messaging for purity.
Changes to intents, leases, retry budgets or worker topology need their own authorized reliability task.
Do not log secrets, learner responses, hidden answers or raw provider error bodies.

## Verification

Run focused tests for rules, authorization, strict providers and persistence touched.
Production changes require full `venv/Scripts/python.exe -m pytest -q` (`pytest.ini` points at `tests/`). Tests live in `tests/<module>/`, operational scripts in `scripts/<module>/`.
Unit tests use injected fakes, not live Supabase/Redis/LLM quotas.
RPC/security changes require authorized real database rollback/concurrency tests.
Jobs require a real broker/process proof when deployment reliability is claimed.
Client contracts require Flutter/Web adapter checks proportional to the change.
Document skips and warnings; structural moves must keep the full suite and import-linter green.
For docs-only work verify links, ownership coverage and absence of runtime/schema diff.
