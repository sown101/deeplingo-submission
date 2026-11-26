> **LEGACY — archived 2026-10-25.** Rules written before the project was redesigned. They record past hypotheses, not settled truth. Relative links below no longer resolve from this folder.

# Flutter V2 engineering rules

Inherit [root governance](../AGENTS.md).
Read [data authority](../docs/architecture/DATA_AUTHORITY.md) before contract edits.
This frontend is production Flutter V2; `../mobile_app` is read-only reference.
This file does not redesign the app or authorize a feature.
Feature freeze from 2026-10-19 to the end of M2 ([STATUS](../docs/product/STATUS.md)):
only fixes for breakage, security and backend compatibility.

## Ownership

- `core/`: auth/session, JWT injection, API/error handling, media adapters.
- `app/`: composition, guarded navigation, shell and lifecycle integration.
- `features/*/domain`: frontend values and repository contracts, not pedagogy.
- `features/*/data`: transport mapping and concrete repositories.
- `features/*/application`: feature BLoC orchestration.
- `features/*/presentation`: widgets, pages and renderer implementation.
- `design_system/`, assets and motion: shared visual language.
- Existing Codex infrastructure/business-state and Antigravity visual ownership
  in README remains a coordination convention; do not overwrite either's work.
- Tests follow the feature/contract they prove.

## Orchestration

AuthBloc owns auth business state over AuthRepository/SessionManager.
OnboardingBloc persists backend-supported learning/explanation languages.
ReviewBloc and LearningSessionBloc remain separate UI orchestrators.
Share `features/shared/activity` rendering, answer values and Attempt/Assessment adapter.
Review compatibility wrappers do not justify a second activity implementation.
Renderers collect input and display server feedback; never grade locally.
Completion and next activity come from backend responses.
Do not infer completed Evidence from a submitted answer or local navigation.
Do not invoke APIs directly from presentation when a repository/BLoC owns them.
Reuse design tokens/components; no drive-by visual redesign in backend work.

## Backend contract

Use learner-facing V3 endpoints and authenticated JWTs through ApiClient.
Never send authoritative user_id, score, Evidence, mastery, skills or FSRS targets.
IDs in URLs are selectors; the backend must authorize them.
Store only learner-facing execution, input, safe feedback and necessary receipts.
Do not decode hidden answers, expected-response payloads, rubrics, semantic targets,
review versions, internal diagnostics or evidence policies into presentation models.
Safe Concept explanations are content, not permission to fetch hidden grading data.
Support language is explanation/response language, not necessarily UI locale.
OccurrenceText uses backend codepoint spans with UTF-16 presentation conversion.
Never rediscover occurrences using substring matching or local Concept inference.
Media errors are recoverable presentation failures, not assessed learner evidence.
Use only Supabase publishable/anon key; no service-role/provider credentials.

## Retry and lifecycle

Read-only projections may be retried; explicit start/resume uses backend identity.
The `next` GET currently materializes activities; treat its retry as server-managed,
not as proof that every GET is side-effect-free.
Retry assessment with the same durable Attempt receipt.
Persist principal-scoped pending UUID/raw response before Attempt POST. After an ambiguous outcome, reconcile only that exact original command; never regenerate a UUID or replace the answer. SharedPreferencesAsync acknowledgement is required before sending; storage failures fail closed. Recovery fetches server execution, reuses a known receipt for Assessment, and clears pending only after parsed feedback. Logout/account switches clear and fence late callbacks. Report unexecuted real DB/device restart gates; do not fabricate completion.
Handle 401/session invalidation centrally and clear feature state on user changes.
Password-reset completion/deep links remain an explicitly unimplemented contract.

## Verification

Run focused repository, BLoC, renderer and wrong-authority tests as appropriate.
Production Dart changes require `flutter analyze` and `flutter test`.
UI/platform/media/auth changes need proportionate device integration verification.
Keep unit tests independent of real tokens, provider quota and shared account state.
Live E2E must use authorized development accounts and protect shared content.
Do not send confirmation links, passwords or tokens in logs/chat.
Check loading/error/empty/retry/completion states, not only happy-path screenshots.
Document actual coverage and skipped platform verification without exaggeration.
For documentation-only changes, check links and no production contract diff.
