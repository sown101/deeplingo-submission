> **LEGACY — archived 2026-10-25.** Rules written before the project was redesigned. They record past hypotheses, not settled truth. Relative links below no longer resolve from this folder.

# DeepLingo engineering constitution

## Mission

DeepLingo turns trusted real content into an adaptive learning loop that takes
learners from recognising language to using it, with a companion that guides practice.
The [product vision](docs/product/PRODUCT_VISION.md) sets product direction; the current
milestone, its spec and the frozen/deferred areas are in [STATUS](docs/product/STATUS.md).
Keep existing contracts working while extending them.
The backend owns pedagogy; clients present it and submit learner interaction.
Backend module boundaries are machine-checked; other rules are enforced by review and tests.

## Repository ownership

- `backend/`: canonical backend/domain authority; FastAPI, PostgreSQL/Supabase, Celery and AI.
- `deeplingo_app/`: active Flutter V2 mobile presentation client.
- `deeplingo_web/`: active React/TypeScript web presentation client.
- `mobile_app/`: read-only legacy reference; do not extend its product behavior.
- `docs/architecture/`: canonical cross-project architecture, ADRs and database schema/ERD.
- `docs/runbooks/`: operational procedures that still apply.
- `docs/product/`: current product concepts and plans.
- Tests and smoke scripts belong with the component they verify.
- Local secrets, attachments, logs and temporary account state are not source.

## Sources of truth

Read the relevant documents before changing the boundary they describe.

- [Current status and frozen areas](docs/product/STATUS.md)
- [Product vision](docs/product/PRODUCT_VISION.md)
- [Architecture](docs/architecture/ARCHITECTURE.md)
- [Domain model](docs/architecture/DOMAIN_MODEL.md)
- [Backend boundaries](docs/architecture/BACKEND_BOUNDARIES.md)
- [Data authority](docs/architecture/DATA_AUTHORITY.md)
- [Active frontend architecture](docs/architecture/FRONTEND_ARCHITECTURE.md)
- [Scaling strategy](docs/architecture/SCALING_STRATEGY.md)
- [Debt register](docs/architecture/DEBT_REGISTER.md)
- [ADR index](docs/architecture/adr/README.md)
- [Optional agent toolchain selection](docs/architecture/AGENT_TOOLCHAIN.md)
- [AI provider environment policy](docs/architecture/AI_PROVIDER_POLICY.md)
- [Runbooks](docs/runbooks/)
- [Backend rules](backend/AGENTS.md)
- [Flutter rules](deeplingo_app/AGENTS.md)
- [React web rules](deeplingo_web/AGENTS.md)

Per-round task records live in git history (commit `12eeee3`); they are evidence of
their round, not current policy (e.g. pre-5L-4 surface-only Concept identity is superseded).
OpenCode is a coding tool, not a DeepLingo runtime provider.
Speech is authorized only as non-evidential practice scoped by ADR-014; the product
vision plans to revisit this through a new ADR, which does not change the rule today.
Word meanings follow ADR-017: dictionaries are the source of truth, the LLM selects senses.

## Instruction precedence

Platform safety and explicit authorization requirements always apply.
Within project engineering decisions, resolve instructions in this order:

1. This root constitution.
2. Accepted architecture decision records.
3. Canonical architecture documents.
4. Applicable local/module AGENTS.md.
5. Current task specification.
6. Optional external skills.
7. Coding-agent defaults.

A task can propose changing architecture but cannot silently override it.
When a task conflicts with a rule, state the conflict and request owner approval.
Update the decision and affected documents in an explicitly approved change.
Local rules specialize their scope; they cannot weaken root invariants.
External workflow guidance is advisory and never a required runtime dependency.
Do not install agent toolchains unless the task explicitly authorizes installation.

## Working cadence

Approval is per milestone: an owner-approved milestone spec authorizes its listed slices.
A slice needs fresh approval only when it changes an invariant, an ADR, assessment or
Evidence policy, or a live environment; a new migration is named in its slice.
Write an ADR only for hard-to-reverse decisions (authority, Evidence, persistence,
providers, security). Deferring an ADR is recorded in its Status and STATUS; it does
not supersede it.
Running progress lives only in STATUS; plans hold intent, not status lines.
Frozen and deferred areas listed in STATUS are not extended without owner approval.

## Architecture

Use a modular monolith with business ownership before technical layering.
The layering below is the backend target, not mandatory frontend ceremony.
Flutter and React are independent feature-first presentation clients with thin
API contracts and server-owned pedagogy; neither depends on the other or legacy app.
Share API/product semantics, not a second frontend domain-authority package.
The canonical bounded modules are identity, content, learning, assessment,
learner and review. Library is part of content.
One PostgreSQL system can support multiple business owners and atomic effects.
Separate API and worker processes do not make the system microservices.
Do not introduce Neo4j into the V3 learning path.
Do not create modules solely for symmetry or folder aesthetics.

Within a module:

`API -> Application -> Domain`

Application depends on abstract ports; infrastructure implements them.
Bootstrap selects implementations and supplies configuration.
Domain must not import FastAPI, Supabase, SQL drivers, Redis, Celery,
HTTP clients, vendor SDKs, environment settings or client transport DTOs.
Domain rules may use standard types and vendor-neutral validated values.
Pydantic alone does not establish a boundary: classify each model by purpose.
External ports belong to the module that consumes the capability.
Do not use a global service locator or a shared-kernel dumping ground;
`app/kernel` admits only values meeting the ADR-015 admission rule.
Cross-module calls use narrow application contracts, not another module's tables.
Preserve critical cross-module database transactions during migration.
Internal synchronous coordination is acceptable; distributed messaging is not required.

## Domain invariants

- DictionaryEntry is linguistic reference, not a Concept or an occurrence.
- Concept is semantic-sense identity, not just normalized surface text.
- LearningObject is one exact trusted occurrence of a Concept.
- ConceptMastery is concept-specific learning, not broad Skill or scheduling.
- LearnerSkillState is language/skill aggregation, not a Concept score.
- ReviewState is per-learner, per-Concept, per-ReviewMode scheduling.
- ReviewMode is not an alias for ActivityType.
- Attempt records learner input; Assessment evaluates it; Evidence is policy-approved signal.
- AssessmentApplication marks durable application of one authoritative Assessment.
- FSRS math belongs only in FSRSAdapter.
- Exposure or viewing alone cannot fabricate strong assessed mastery.
- Unsupported enum values do not constitute modality enablement.

## Authority

Derive V3 learner identity from verified CurrentUser.
Recheck ownership when resolving Library, session, activity and Attempt IDs.
Client IDs select resources to authorize; they are not proof of ownership.
Client language preferences are requests validated against supported languages.
Execution language is resolved from persisted server context.
Backend chooses Concept, occurrence, activities, ReviewMode and expected answers.
Backend determines scores, Evidence, mastery, skills, FSRS and completion.
Backend configuration chooses provider/model; clients cannot override them.
Never accept client grading, learner-state targets or review ratings as authority.
M1 flows change learner state only through assessed Quick review MCQ updating
ReviewState; they neither write nor read ConceptMastery or LearnerSkillState
([data authority](docs/architecture/DATA_AUTHORITY.md#m1-learning-flow-boundary)).
Public content reads are not a learner-state mutation permission.
Never expose service-role keys or provider credentials to clients.
Never reintroduce caller-supplied user IDs or other legacy authority patterns.

## LLM rules

LLMs can propose grounded content and structured judgments, not learner state.
Keep strict schemas, required fields, enum constraints and extra-field rejection.
Keep score/confidence bounds, confidence policy, leakage and injection protections.
Never parse arbitrary prose with regex to bypass canonical structured contracts.
Fail closed on missing context, invalid structure, refusal or provider failure.
Do not interpret provider outage as evidence of learner failure.
Do not silently switch providers or let a provider choose pedagogy.
Prompt changes require versions and contract tests in their consuming module.
Qualification is environment/model/task-specific, not a blanket SDK guarantee.

## Think before coding

Read existing code, tests and history relevant to the requested behavior.
State important assumptions and unresolved choices before consequential changes.
Define scope and observable success criteria before implementation.
Separate diagnosis, proposals and authorized implementation.
Choose the simplest sufficient solution that preserves trusted contracts.
Explain meaningful tradeoffs with concrete evidence.
Prefer vertical slices over mechanical whole-tree moves.
Keep edits surgical; do not perform drive-by cleanup.
Preserve dirty worktrees and changes owned by other people or agents.
Do not overwrite user work or use destructive Git recovery.
Do not claim proof from a historical test result as a newly run test.

## Scope and migration

Documentation tasks do not authorize runtime behavior or schema changes.
Boundary migrations preserve URLs, JSON contracts, stable IDs and policies.
Backend moves are hard cuts without compatibility shims (ADR-015).
Avoid duplicate scoring, assessment, review or content pipelines.
Do not keep code only because it exists. A slice that replaces an implementation moves every
caller and deletes the old one in the same change; code with no remaining caller (API, web,
Flutter, worker/Beat, scripts, stored sessions) goes with its tests and docs. Hidden or deferred
is not proof of disuse.
Do not change policy weights, thresholds or FSRS parameters during code movement.
Keep transactional state application synchronous and atomic.
Split reliability improvements into explicitly scoped tasks after boundary work.
Do not add Speech or other post-V1 modalities without a separate authorized task.
Microservice extraction requires the criteria in the scaling strategy and an ADR.

## Database rules

PostgreSQL is the durable source of truth; Redis is transport/cache only.
Use migrations for schema/grants/RLS changes, not undocumented dashboard edits.
Never rewrite deployed migrations or blindly replay the legacy baseline.
Record intended environment and obtain authorization before live mutations.
Service-role access bypasses RLS: server ownership checks remain mandatory.
Separate own-profile/organizational writes from pedagogical state writes.
Keep RPC privileges narrow and search paths explicit.
SQL commits server-computed effects; it does not duplicate grading or FSRS.
Keep external HTTP/LLM calls outside database transactions.
Idempotency and compare-and-swap are business contracts, not optional optimizations.
Unknown write outcomes must be reconciled; do not blindly retry append-only commands.
Deleting learner test data must not delete shared global content.

## Verification

Use focused tests for the affected invariant and owner boundaries.
Run full backend regression for production backend changes.
Run Flutter tests and analysis for production Flutter changes.
Run web typecheck/tests/build and affected browser gates for production React changes.
Use integration tests for auth, RPC/concurrency and process boundaries when changed.
Normal tests must not depend on live AI credentials or quota.
Live gates require an authorized non-production environment and cleanup plan.
Check schema/leakage/injection gates when prompts or providers change.
Test wrong-owner and forbidden-authority paths, not only happy paths.
Document skipped tests, warnings, unavailable infrastructure and remaining debt.
Documentation-only work requires link, consistency and scope verification.

## Definition of done

Requested scope is implemented or a precise blocker is reported.
Affected owners, contracts, invariants and failure paths are accounted for.
Verification evidence matches exactly what was run.
No accidental production, schema, API or dependency changes remain.
Documentation distinguishes current behavior from target and proposed work.
Secrets and temporary artifacts are absent from the deliverable.
The handoff states remaining risks and one relevant next task.
Do not start that next task without authorization.
