-- DRAFT. Not applied to any environment. Applying it needs the owner's approval for that environment, and it deletes
-- data. Development only: these objects belong to the previous product, are not created by any migration in this
-- repository, and exist only on the development database.
-- A read-only catalog query of development (2026-11-15) showed: nothing in schema v3 or any other schema depends on
-- them (no foreign key, view or function body); the only dependents are their own policies, triggers and each other.
-- Names are explicit; there is no drop schema and no cascade on anything not named here. Extension objects in public
-- (pg_trgm: similarity, show_trgm, gtrgm_*, gin_*_trgm, word_similarity*, strict_word_similarity*, set_limit,
-- show_limit) are NOT touched. Types in public were not checked.

-- 1. Views and the materialized view.
drop view if exists public.v_smart_groups;
drop view if exists public.v_user_library_details;
drop view if exists public.v_videos_with_language;
drop materialized view if exists public.mv_video_stats;

-- 2. Tables (their policies, indexes and triggers go with them). Foreign keys exist between these tables, so cascade
-- is used, and only on tables named here.
drop table if exists public.flashcard_reviews cascade;
drop table if exists public.flashcards cascade;
drop table if exists public.saved_words cascade;
drop table if exists public.user_vocabulary_progress cascade;
drop table if exists public.vocabulary_master cascade;
drop table if exists public.word_group_members cascade;
drop table if exists public.word_groups cascade;
drop table if exists public.subtitles cascade;
drop table if exists public.learning_activities cascade;
drop table if exists public.user_library cascade;
drop table if exists public.channels cascade;
drop table if exists public.videos cascade;
drop table if exists public.language_config cascade;
drop table if exists public.user_language_preferences cascade;

-- 3. Functions of those tables (identity arguments read from the development catalog).
drop function if exists public.auto_create_flashcard();
drop function if exists public.compute_word_count();
drop function if exists public.find_word_in_videos(text, character varying, integer);
drop function if exists public.get_due_flashcards(uuid, uuid, integer);
drop function if exists public.get_romanization(jsonb, character varying);
drop function if exists public.get_translation(jsonb, character varying, character varying);
drop function if exists public.refresh_video_stats();
drop function if exists public.search_subtitles(text, text, character varying);
drop function if exists public.set_updated_at();
drop function if exists public.sync_video_available_translations();
drop function if exists public.sync_word_group_count();
drop function if exists public.update_video_on_ai_ready();
drop function if exists public.update_video_on_subtitle_insert();
drop function if exists public.upsert_romanization(jsonb, text, text);
drop function if exists public.upsert_translation(jsonb, character varying, text);
drop function if exists public.videos_search_vector_update();
