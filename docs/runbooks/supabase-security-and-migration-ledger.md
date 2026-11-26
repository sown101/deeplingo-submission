# Supabase security posture and migration ledger

## Scope and environment

This round audited and hardened the hosted development project whose configured
project reference is `sqlcckgdfxyrepqawahn`. The runtime reported
`ENVIRONMENT=development`; the migration and destructive smoke guards refuse a
production environment or a project-reference mismatch.

The work is a forward-only security repair. No historical migration file was
edited and no legacy table or development content was dropped.

## Migration history

The hosted migration ledger now tracks the effective 030–035 lineage, the
`repair_review_events_provenance` repair, and the 5L-1 hardening migration.

The effective V3 schema also contains the objects and invariants from local
migrations 001–029, but those older migrations are not represented in the
hosted migration ledger. They must not be blindly replayed: the deployed schema
already contains their objects and data. This is historical-provenance debt,
not current effective-schema drift. Future changes should continue from new,
timestamped, forward migrations. The two local files with a `030_` prefix are a
separate repository naming debt and should not be renamed after deployment.

Dropped later by the cleanup migrations `20261027120000_drop_ai_cost_ledger_b1`,
`20261027130000_drop_mastery_review_session_b3` and `20261027140000_drop_assessments_b4_3`:
`v3.ai_cost_calls`, `v3.ai_budget_scopes`, `v3.review_materializations`, `v3.learner_skill_states`,
`v3.concept_mastery`, `v3.assessment_applications` and `v3.assessments`, with their functions.
The sections marked "at the 5L-1 round" describe the schema as it was then.

## Data API exposure policy

Both `public` and `v3` are reachable through the hosted Data API. Exposure is
therefore controlled by grants and RLS, not by assuming schema obscurity.

| Surface | Direct-client policy | Write authority |
|---|---|---|
| V3 languages, romanization systems, channels, videos, transcripts, segments, translations, dictionary entries, concepts, links, verified learning objects | Public read | Service/server |
| V3 profile | Authenticated own-row read/write for non-learning profile fields | Learner for own display profile |
| V3 language profile | Authenticated own-row read | FastAPI/service only |
| V3 sessions, activities, attempts | Authenticated own-row read | FastAPI/service only |
| V3 review state, review events | Authenticated own-row read | FastAPI/service only |
| V3 saved concepts, word groups, word-group items | Authenticated own-row read/write | Learner organizational data |
| V3 companion settings and companion memory | Authenticated own-row read | FastAPI/service only |
| V3 curriculum levels, grammar points, units and unit targets | Public read | Service only, through `v3.load_curriculum_level(jsonb)` |
| Legacy public content tables and public content views | Public read | Service/server only |
| Legacy public learner tables and learner views | Authenticated own-row read | Service/server only |
| `public.mv_video_stats` | Public read-only aggregate | Service maintenance only |

The legacy learner tables are retained because they contain development data
and are still referenced by the old application. Their direct mutation surface
is closed. The current Frontend V2/V3 product path uses authenticated FastAPI
routes and the service-role client.

## RLS model

RLS is enabled on every application table in the exposed `public` and `v3`
schemas. Public content uses explicit read-only policies. Learner rows use
`(select auth.uid()) = user_id`, or an ownership join where the table has no
direct `user_id` column.

Authenticated `INSERT`, `UPDATE`, and `DELETE` grants were removed from:

- learning sessions, session activities, and attempts;
- review states and review events.

The mutating RLS policies left by migration 029 on sessions,
activities, and attempts were removed. Own-row read policies remain.

## Server-only authority

FastAPI derives the learner identity from a verified Supabase JWT and performs
current V3 persistence with the service-role client. Database grants now match
that architecture. A client bypassing the app cannot directly set session state, graded answers,
FSRS fields or ratings.

Language-profile behavior remains:

- own-row direct read is allowed;
- direct authenticated mutation is denied;
- the authenticated FastAPI service path can write through service authority.

## Critical RPC policy

The following functions are `SECURITY INVOKER`, owned by `postgres`, have the
explicit `v3, extensions` search path, and are executable by `service_role` but
not by `anon` or `authenticated`:

- `v3.submit_graded_attempt(jsonb)` (B4.2; replaces the dropped assessment application RPCs of B4.3)
- `v3.load_curriculum_level(jsonb)` (empty search path, global reference content only)

Their input identities remain checked by the existing transactional contracts.
5L-1 reasserts their grants without creating a second authority path.

## Views and functions

The three legacy views flagged as security-definer equivalents now use
`security_invoker=true`, so caller grants and base-table RLS apply:

- `public.v_videos_with_language`
- `public.v_user_library_details`
- `public.v_smart_groups`

All 16 application-owned legacy functions flagged for mutable search paths now
use the explicit `public, pg_temp` path. Trigger functions cannot be invoked by
Data API roles. `get_due_flashcards` and `refresh_video_stats` are service-only.
Read-only content helpers retain explicit anon/authenticated execution.

There are no elevated `SECURITY DEFINER` application functions in the audited
critical V3 or legacy function set.

## Foreign-key indexes

The pre-change advisor/query audit found 28 uncovered foreign keys: 10 in the
active legacy schema and 18 in V3. The migration added named indexes for all 28.
They cover current or growing joins and FK update/delete checks, including
attempt/user, concept, review state, session, learning object, transcript
segment, and language references. The post-change audit reports zero uncovered
foreign keys in `public` and `v3`.

## Review-event and 030–035 invariants (at the 5L-1 round)

The hosted schema now verifies all of the following:

- one authoritative assessment per attempt;
- required, unique assessment linkage on review events;
- provenance on review events;
- both scheduling-snapshot payload leak constraints;
- assessment-application table and transactional RPC;
- review-materialization table and reservation RPC;
- review-session orchestration RPC;
- materialization lifecycle transition RPCs;
- support-language linkage on the authoritative learner language profile.

No duplicate repair constraint was created.

## Verification (at the 5L-1 round)

`scripts/platform/smoke_supabase_security.py` creates two temporary hosted-development
Auth users and proves:

- learner A cannot read learner B's profile or skill-state rows;
- learner A can read their own profile and skill state;
- direct language-profile, skill-state, and Attempt writes are rejected;
- authenticated invocation of the critical session RPC is rejected;
- anonymous authority reads are rejected while intended public content reads;
- FastAPI/service initialization, language-profile write, and skill read work;
- all temporary users and rows are removed.

The existing semantic-review smoke additionally passed the positive and
negative assessment paths, idempotent retry, Attempt persistence, Assessment,
AssessmentApplication, mastery/skill update, ReviewEvent, ReviewState/FSRS
transition, session completion, language-profile security, and cleanup. Its
controlled provider-failure case preserved the Attempt and left learner state
unchanged.

## Advisor comparison (at the 5L-1 round)

Before 5L-1, security advisors reported 14 public tables without RLS, three
security-definer-equivalent views, and 16 mutable function search paths. The
performance audit reported 28 uncovered foreign keys.

After 5L-1, all of those findings are cleared. Remaining findings are:

- `pg_trgm` is installed in `public`: accepted legacy debt for this round;
  relocating an installed extension requires a separately tested dependency
  migration.
- `public.mv_video_stats` is visible to the Data API: accepted intentionally as
  a read-only aggregate of public content; refresh execution is service-only.
- leaked-password protection is disabled: dashboard/Auth configuration debt
  that must be enabled before a production launch.
- unused-index notices: observational/future optimization only. New FK indexes
  naturally begin with zero usage, and no index was removed without workload
  evidence.

Advisor references:

- [Extension in public schema](https://supabase.com/docs/guides/database/database-linter?lint=0014_extension_in_public)
- [Materialized view in Data API](https://supabase.com/docs/guides/database/database-linter?lint=0016_materialized_view_in_api)
- [Password security](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)

## Remaining production debt

The database authority boundary is suitable as a production baseline with
known debt. Before an actual production launch:

1. enable leaked-password protection in Supabase Auth;
2. establish a clean production migration baseline rather than replaying the
   incomplete hosted-development history;
3. either retire the unauthenticated legacy FastAPI routers that accept
   caller-supplied user IDs or migrate them to the V3 JWT identity model;
4. evaluate relocating `pg_trgm` outside `public` in a dedicated migration;
5. keep the intentionally public materialized-view decision under review if its
   fields expand beyond public content statistics.

The current Frontend V2 contract and Flutter code require no change.
