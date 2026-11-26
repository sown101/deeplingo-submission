-- DeepLingo v3 migration 028: query-driven indexes.

create unique index if not exists user_language_preferences_one_primary_idx
  on v3.user_language_preferences (user_id)
  where is_primary;

create index if not exists channels_source_external_idx
  on v3.channels (source, external_channel_id);

create index if not exists videos_language_status_idx
  on v3.videos (original_language_code, processing_status);

create index if not exists videos_channel_id_idx
  on v3.videos (channel_id);

create index if not exists video_transcripts_video_language_idx
  on v3.video_transcripts (video_id, language_code);

create index if not exists transcript_segments_transcript_time_idx
  on v3.transcript_segments (transcript_id, start_ms, end_ms);

create index if not exists segment_translations_language_idx
  on v3.segment_translations (language_code);

create index if not exists segment_romanizations_system_idx
  on v3.segment_romanizations (romanization_system_id);

create index if not exists dictionary_entries_lookup_idx
  on v3.dictionary_entries (language_code, normalized_headword);

create index if not exists concepts_lookup_idx
  on v3.concepts (language_code, type, normalized_text);

create index if not exists concept_dictionary_links_dictionary_idx
  on v3.concept_dictionary_links (dictionary_entry_id);

create index if not exists learning_objects_concept_idx
  on v3.learning_objects (concept_id, extraction_status);

create index if not exists learning_objects_video_segment_idx
  on v3.learning_objects (video_id, transcript_segment_id);

create index if not exists learner_skill_states_user_language_idx
  on v3.learner_skill_states (user_id, language_code);

create index if not exists concept_mastery_user_state_idx
  on v3.concept_mastery (user_id, state, updated_at desc);

create index if not exists learning_sessions_user_status_idx
  on v3.learning_sessions (user_id, status, created_at desc);

create index if not exists session_activities_session_position_idx
  on v3.session_activities (session_id, position);

create index if not exists attempts_user_submitted_idx
  on v3.attempts (user_id, submitted_at desc);

create index if not exists attempts_activity_user_idx
  on v3.attempts (activity_id, user_id);

create index if not exists assessments_attempt_idx
  on v3.assessments (attempt_id);

create index if not exists review_states_due_idx
  on v3.review_states (user_id, due_at, fsrs_state);

create index if not exists review_states_concept_mode_idx
  on v3.review_states (user_id, concept_id, review_mode);

create index if not exists review_events_reviewed_idx
  on v3.review_events (review_state_id, reviewed_at desc);

create index if not exists saved_concepts_user_created_idx
  on v3.saved_concepts (user_id, created_at desc);

create index if not exists word_groups_user_language_idx
  on v3.word_groups (user_id, language_code, created_at desc);

create index if not exists word_group_items_saved_concept_idx
  on v3.word_group_items (saved_concept_id);
