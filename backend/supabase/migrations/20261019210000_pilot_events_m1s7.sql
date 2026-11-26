-- M1 S7 (pilot preparation): the practice log records where a session starts and ends.
--
-- `region_opened`: the learner chose a new study part (server-checked range).
-- `session_summarized`: the learner finished and the server summarized what they practised.
-- `companion_turn`: one successful companion turn about this video (the fact and turn number only;
-- no words, audio or reply). A companion conversation may happen before any part is chosen, so this
-- kind alone may leave the sentence (and transcript) empty.
-- These feed the end-of-session summary and the pilot measurement. Still practice only: never an
-- Attempt, Evidence, mastery, skill or ReviewState; same 90-day expiry. Forward-only.

alter table v3.learner_practice_events drop constraint if exists learner_practice_events_kind_check;
alter table v3.learner_practice_events add constraint learner_practice_events_kind_check
  check (kind in ('dictation_checked', 'shadowing_attempted', 'word_lookup', 'region_question_answered',
                  'region_opened', 'session_summarized', 'companion_turn'));

alter table v3.learner_practice_events alter column transcript_id drop not null;
alter table v3.learner_practice_events alter column segment_id drop not null;
alter table v3.learner_practice_events drop constraint if exists learner_practice_events_sentence_chk;
alter table v3.learner_practice_events add constraint learner_practice_events_sentence_chk
  check ((transcript_id is not null and segment_id is not null) or kind = 'companion_turn');
