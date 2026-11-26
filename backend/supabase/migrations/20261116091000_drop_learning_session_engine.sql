-- DRAFT. Not applied to any environment. Applying it needs the owner's approval for that environment, and it deletes
-- learner rows (sessions, activities, attempts, old grammar results). Run it only after the backend without the
-- learning-session engine is deployed. Forward-only.
--
-- The Flutter app (the only caller of the session engine) was removed and the web no longer calls it, so the backend
-- no longer reads or writes these tables:
--   learning_sessions, session_activities, attempts   quick review batches, known checks, video practice sessions
--   learner_grammar_review_results                    the old grammar review answers (copied into
--                                                     learner_grammar_progress by 20261114120000_review_engine)
-- Kept on purpose: learner_quick_review_skips (dropped separately by 20261116094000, with its last readers),
-- learner_practice_events (the practice log still writes and exports it), learner_known_concepts (read and removed by
-- the Notebook; its two provenance columns known_check_session_id and attempt_id stay as plain uuid columns once their
-- foreign keys are dropped here), review_events (its attempt_id column stays, without the foreign key).
-- Order: functions that use the tables, foreign keys from live tables, the tables (their indexes, policies and
-- triggers go with them), the two trigger functions, then the enum types only these tables used.

drop function if exists v3.mark_concept_known(uuid, uuid);
drop function if exists v3.materialize_session_activity_if_absent(uuid, uuid, jsonb, jsonb);
drop function if exists v3.quick_review_next_snapshot(uuid, uuid);
drop function if exists v3.skip_quick_review_item(uuid, uuid, uuid);
drop function if exists v3.start_or_resume_known_check_session(uuid, uuid, uuid, uuid, uuid, text, text, text, text[]);
drop function if exists v3.start_or_resume_quick_review_session(uuid, text, text, text, jsonb);
drop function if exists v3.submit_graded_attempt(jsonb);

alter table v3.learner_known_concepts drop constraint if exists learner_known_concepts_known_check_session_id_fkey;
alter table v3.learner_known_concepts drop constraint if exists learner_known_concepts_attempt_id_fkey;
alter table v3.review_events drop constraint if exists review_events_attempt_id_fkey;

-- learning_objects.supported_activity_types was a column of the old activity engine (type v3.activity_type[]);
-- no backend code reads or writes it (the model field has a default only). Dropped here so the type can go.
alter table v3.learning_objects drop column if exists supported_activity_types;
drop table if exists v3.attempts;
drop table if exists v3.session_activities;
drop table if exists v3.learning_sessions;
drop table if exists v3.learner_grammar_review_results;

drop function if exists v3.protect_immutable_attempt();
drop function if exists v3.guard_materialized_activity_payload();

drop type if exists v3.attempt_status;
drop type if exists v3.activity_status;
drop type if exists v3.activity_type;
drop type if exists v3.learning_session_status;
drop type if exists v3.learning_session_type;
