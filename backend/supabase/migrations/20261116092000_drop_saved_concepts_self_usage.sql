-- DRAFT. Not applied to any environment. Applying it needs the owner's approval for that environment.
-- Forward-only. The "can use" self-rating was removed from the web and the server (owner decision 2026-11-15) and the
-- Flutter-only response field is gone too, so nothing reads or writes saved_concepts.self_usage any more.
-- The check constraint saved_concepts_self_usage_check goes with the column. The values are not carried over.

alter table v3.saved_concepts drop column if exists self_usage;
