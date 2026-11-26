-- Index cleanup (review finding). WRITTEN, NOT APPLIED to any environment: applying it needs the owner's approval.
--
-- Added (plain indexes; the existing ones on these columns are partial or have another leading column):
--   * learner_pronunciation_scores(occurred_at): the retention job deletes by occurred_at alone, the existing index
--     starts with user_id.
--   * video_work_intents(video_id) and video_work_intents(region_preparation_id): the foreign keys' cascade and the
--     workers' lookups; the unique indexes on both columns are partial and cannot serve them.
create index if not exists learner_pronunciation_scores_occurred_idx
  on v3.learner_pronunciation_scores (occurred_at);
create index if not exists video_work_intents_video_idx
  on v3.video_work_intents (video_id);
create index if not exists video_work_intents_region_preparation_idx
  on v3.video_work_intents (region_preparation_id) where region_preparation_id is not null;

-- Dropped: each index below has the same leading columns as a unique constraint on the same table, so the
-- constraint's own index serves every query the extra index serves.
--   channels_source_external_idx            (source, external_channel_id)               = channels_source_external_unique
--   companion_proposals_plan_idx            (plan_id, position)                         = companion_proposals_position_unique
--   concepts_lookup_idx                     (language_code, type, normalized_text)      prefix of concepts_unique_semantic_identity
--   dictionary_entries_lookup_idx           (language_code, normalized_headword)        prefix of dictionary_entries_unique_headword
--   review_states_concept_mode_idx          (user_id, concept_id, review_mode)          = review_states_unique_mode
--   video_transcripts_video_language_idx    (video_id, language_code)                   prefix of video_transcripts_unique_track
--   word_group_import_rows_group_idx        (group_id, position)                        = word_group_import_rows_position_unique
drop index if exists v3.channels_source_external_idx;
drop index if exists v3.companion_proposals_plan_idx;
drop index if exists v3.concepts_lookup_idx;
drop index if exists v3.dictionary_entries_lookup_idx;
drop index if exists v3.review_states_concept_mode_idx;
drop index if exists v3.video_transcripts_video_language_idx;
drop index if exists v3.word_group_import_rows_group_idx;

-- NOT dropped: review_events_attempt_idx (review_events.attempt_id). No unique constraint covers that column, and
-- the index may serve the foreign key to v3.attempts; unconfirmed until the owner checks usage on the database.
