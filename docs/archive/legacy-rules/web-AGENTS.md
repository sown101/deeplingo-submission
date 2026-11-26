> **LEGACY — archived 2026-10-25.** Rules written before the project was redesigned. They record past hypotheses, not settled truth. Relative links below no longer resolve from this folder.

# React web engineering rules

Inherit [root governance](../AGENTS.md); read
[frontend architecture](../docs/architecture/FRONTEND_ARCHITECTURE.md) and
[data authority](../docs/architecture/DATA_AUTHORITY.md) before boundary changes.
This is an active production presentation client, not a Flutter reference port.
Production readiness remains gated by documented debt; this file does not enable features.
Web is the M1 pilot client; scope is the [M1 spec](../docs/product/M1_VIDEO_SESSION_SPEC.md).

## Feature ownership

- app: composition, shell, guarded routing, auth lifecycle and error/loading boundaries.
- features: product screens, thin API adapters, safe mappings and local workflows.
- lib: transport/config/auth/navigation/Unicode support, not business policy.
- features/shared/activities: renderers, answer/feedback values and Attempt API reuse.
- Reuse existing CSS tokens/components in src/styles.css; do not reorganize for symmetry.
- Keep feature-first architecture; do not reproduce backend Clean Architecture ceremony.
- Separate Practice/Review reducers are UI orchestrators, not alternative learner engines.
- Do not depend on deeplingo_app or legacy mobile_app, or add a shared frontend domain package.

## Contracts and forbidden authority

Use learner-facing V3 endpoints through ApiClient and feature-owned safe decoders.
Only learner interaction/raw_response and validated preference requests are commands.
Resource IDs are selectors; backend verifies JWT identity and ownership.
Backend alone resolves Concept/occurrence, selects activities/ReviewMode, grades, creates
Evidence, updates mastery/skills/review/FSRS/due dates and determines progression.
Never submit authoritative user_id, scores, correct answers, ratings or state targets.
Never model/render hidden answers/rubrics/semantic grading context, provider secrets,
FSRS internals or raw diagnostics. Safe Concept meanings are content, not grading access.
Display server scores as projections; do not calculate proficiency from exposure.
Require explicit backend completion and counts; null activity/submission is not completion.
Reject unsupported/inconsistent states; never fabricate content or learning gain.
Use trusted codepoint spans with UTF-16 conversion; never discover occurrences by search.
Keep current handwritten contracts aligned with reviewed API semantics and parity fixtures.
No codegen/internal model export or schema weakening without a separately approved task.

## Auth and state boundaries

Use browser publishable/anon config only; no service-role/AI/DB/broker keys in VITE values.
Supabase session/localStorage and route guards are UX, not authorization boundaries.
FastAPI verifies Bearer JWT; no caller-controlled identity or direct pedagogical DB writes.
Keep refresh/session/401/logout handling centralized and failures visible.
Scope learner caches by identity and relevant language/resource; cancel/fence stale work
and discard old-user cache/receipts on identity change. Preserve the 6B-1A private
scope/public-catalog split and keyed workflow reset. Backend onboarding remains authoritative.
TanStack Query holds server projections; reducers/forms/refs hold transient UI state.
Do not build a global store for mastery, review scheduling or progression authority.
Use guarded React Router routes and safe internal return locations; no open redirects.

## Retry, browser presentation and accessibility

Bound request budgets; do not silently multiply expensive lifecycle retries.
Assessment retry reuses the same Attempt receipt. 6B-1C-R stores principal-scoped pending UUID/raw response in a strict-durability IndexedDB transaction before POST; old localStorage records are same-principal migration input only. Reload/route/process-restart recovery retries only the exact original keyed command, never a regenerated key or changed answer. Storage failure blocks sending. Logout/account switch clears/quarantines pending and fences late responses; no persisted execution/feedback authority. The live proof is development-only, not arbitrary power-loss certification.
The next GET may materialize on the server; its semantics differ from ordinary reads.
Local media errors/position are not failure Evidence or completion.
Use trusted media identifiers/origins and validate postMessage source/origin.
Preserve responsive layout, labels/statuses, keyboard operation, visible focus,
modal focus/escape/restoration and reduced-motion behavior; test actual interactions.
Reuse design patterns rather than drive-by visual redesign; semantics match Flutter,
not necessarily pixels or platform navigation.

## Verification

Use existing package scripts: typecheck, test, build, audit:build, check:bundle
and test:e2e:deterministic as appropriate to changed code. No lint command exists today.
Test malformed DTOs/leakage, auth/account-switch cache isolation, explicit completion,
uncertainty, unsupported activities, ambiguity and same-receipt assessment retry.
Include focused keyboard/modal/narrow-viewport checks for presentation changes.
Fixtures/mocked Playwright are deterministic; live Auth/API/media/provider proof is separate.
Live gates require authorized development learners, secret-safe logs and guarded cleanup;
never delete shared/global content. Record actual results/skips, not historical totals.
Docs-only tasks require links, hierarchy, consistency and no runtime/API/schema changes.
