-- DRAFT. Not applied to any environment. Applying it needs the owner's approval for that environment.
-- Forward-only. Drops v3 functions that no backend code calls (app/ and scripts/ were searched for the names, the
-- dynamic rpc helpers were read, and no other v3 function body, trigger, view or policy references them; checked
-- in the migrations and against a read-only catalog query of the development project on 2026-11-15):
--   * the old per-video content work RPCs, replaced by the leased work intents (admit_/claim_leased_/...);
--   * the old flashcard commit RPCs and the grammar review RPCs, replaced by submit_review_answer and
--     record_grammar_answer (20261114120000_review_engine);
--   * the notebook topic proposal RPC;
--   * create_or_reconcile_attempt and start_or_resume_example_practice_session of the removed learning-session engine.
-- Each drop names the exact argument types and uses if exists, so a re-run is harmless.

drop function if exists v3.apply_notebook_topic_proposal(uuid, text, text, uuid[]);
drop function if exists v3.claim_video_content_work(uuid, text);
drop function if exists v3.complete_transcript_content_work(uuid);
drop function if exists v3.fail_claimed_content_work(uuid, uuid, bigint, text, boolean, integer);
drop function if exists v3.reset_failed_video_content_work(uuid, integer);
drop function if exists v3.commit_flashcard_review(uuid, uuid, jsonb);
drop function if exists v3.flashcard_review_context(uuid, uuid);
drop function if exists v3.create_or_reconcile_attempt(uuid, uuid, uuid, jsonb, timestamp with time zone, timestamp with time zone, integer, jsonb);
drop function if exists v3.grammar_review_summary(uuid);
drop function if exists v3.record_grammar_review_result(uuid, jsonb);
drop function if exists v3.start_or_resume_example_practice_session(uuid, uuid, uuid, text, text, text, jsonb, jsonb);
