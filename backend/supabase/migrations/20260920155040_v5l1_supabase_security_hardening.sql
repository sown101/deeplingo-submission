-- DeepLingo 5L-1: harden Data API access, authority grants, legacy views,
-- function execution, and foreign-key support indexes.

-- ---------------------------------------------------------------------------
-- V3 authority is server-owned. Learners retain the own-row read policies
-- established by 029/031/032, but cannot write execution/evidence/mastery state
-- directly through PostgREST.
-- ---------------------------------------------------------------------------

revoke insert, update, delete on
  v3.learner_skill_states,
  v3.concept_mastery,
  v3.learning_sessions,
  v3.session_activities,
  v3.attempts,
  v3.assessments,
  v3.review_states,
  v3.review_events,
  v3.assessment_applications,
  v3.review_materializations
from authenticated;

drop policy if exists "Users can manage own learner skill states"
  on v3.learner_skill_states;
drop policy if exists "Users can create own learning sessions"
  on v3.learning_sessions;
drop policy if exists "Users can update own learning sessions"
  on v3.learning_sessions;
drop policy if exists "Users can create own session activities"
  on v3.session_activities;
drop policy if exists "Users can update own session activities"
  on v3.session_activities;
drop policy if exists "Users can insert own attempts"
  on v3.attempts;
drop policy if exists "Users can update own unsubmitted attempts"
  on v3.attempts;

drop policy if exists "Users can read own learner skill states"
  on v3.learner_skill_states;
create policy "Users can read own learner skill states"
  on v3.learner_skill_states for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- Reassert the server-only contract for the transactional V3 RPCs. They are
-- SECURITY INVOKER functions with a fixed v3/extensions search_path.
revoke execute on function v3.apply_assessment_application(jsonb)
  from public, anon, authenticated;
revoke execute on function v3.reserve_review_materialization(jsonb)
  from public, anon, authenticated;
revoke execute on function v3.start_or_resume_review_session(uuid, text, jsonb, integer)
  from public, anon, authenticated;
revoke execute on function v3.mark_review_materialization_active(uuid, uuid, uuid)
  from public, anon, authenticated;
revoke execute on function v3.mark_review_materialization_failed(uuid, uuid, uuid, text)
  from public, anon, authenticated;
revoke execute on function v3.review_materialization_result(v3.review_materializations, boolean)
  from public, anon, authenticated;

grant execute on function v3.apply_assessment_application(jsonb)
  to service_role;
grant execute on function v3.reserve_review_materialization(jsonb)
  to service_role;
grant execute on function v3.start_or_resume_review_session(uuid, text, jsonb, integer)
  to service_role;
grant execute on function v3.mark_review_materialization_active(uuid, uuid, uuid)
  to service_role;
grant execute on function v3.mark_review_materialization_failed(uuid, uuid, uuid, text)
  to service_role;
grant execute on function v3.review_materialization_result(v3.review_materializations, boolean)
  to service_role;

-- ---------------------------------------------------------------------------
-- Legacy public schema. Content remains publicly readable. Learner-owned rows
-- are authenticated own-row readable for compatibility, while all mutations
-- are server-owned. The service role remains the legacy FastAPI/worker writer.
-- ---------------------------------------------------------------------------

alter table public.language_config enable row level security;
alter table public.channels enable row level security;
alter table public.videos enable row level security;
alter table public.subtitles enable row level security;
alter table public.vocabulary_master enable row level security;
alter table public.user_library enable row level security;
alter table public.user_language_preferences enable row level security;
alter table public.user_vocabulary_progress enable row level security;
alter table public.learning_activities enable row level security;
alter table public.saved_words enable row level security;
alter table public.word_group_members enable row level security;
alter table public.word_groups enable row level security;
alter table public.flashcards enable row level security;
alter table public.flashcard_reviews enable row level security;

revoke all privileges on all tables in schema public from anon, authenticated;
revoke all privileges on all sequences in schema public from anon, authenticated;

grant select on
  public.language_config,
  public.channels,
  public.videos,
  public.subtitles,
  public.vocabulary_master,
  public.mv_video_stats,
  public.v_videos_with_language
to anon, authenticated;

grant select on
  public.user_library,
  public.user_language_preferences,
  public.user_vocabulary_progress,
  public.learning_activities,
  public.saved_words,
  public.word_group_members,
  public.word_groups,
  public.flashcards,
  public.flashcard_reviews,
  public.v_user_library_details,
  public.v_smart_groups
to authenticated;

grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;

drop policy if exists "Public can read active language config" on public.language_config;
create policy "Public can read active language config"
  on public.language_config for select
  to anon, authenticated
  using (is_active);

drop policy if exists "Public can read channels" on public.channels;
create policy "Public can read channels"
  on public.channels for select
  to anon, authenticated
  using (true);

drop policy if exists "Public can read videos" on public.videos;
create policy "Public can read videos"
  on public.videos for select
  to anon, authenticated
  using (true);

drop policy if exists "Public can read subtitles" on public.subtitles;
create policy "Public can read subtitles"
  on public.subtitles for select
  to anon, authenticated
  using (true);

drop policy if exists "Public can read vocabulary" on public.vocabulary_master;
create policy "Public can read vocabulary"
  on public.vocabulary_master for select
  to anon, authenticated
  using (true);

drop policy if exists "Users can read own library" on public.user_library;
create policy "Users can read own library"
  on public.user_library for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own legacy language preferences"
  on public.user_language_preferences;
create policy "Users can read own legacy language preferences"
  on public.user_language_preferences for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own vocabulary progress"
  on public.user_vocabulary_progress;
create policy "Users can read own vocabulary progress"
  on public.user_vocabulary_progress for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own learning activities"
  on public.learning_activities;
create policy "Users can read own learning activities"
  on public.learning_activities for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own saved words" on public.saved_words;
create policy "Users can read own saved words"
  on public.saved_words for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own word groups" on public.word_groups;
create policy "Users can read own word groups"
  on public.word_groups for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own word group members"
  on public.word_group_members;
create policy "Users can read own word group members"
  on public.word_group_members for select
  to authenticated
  using (
    exists (
      select 1
      from public.word_groups wg
      where wg.id = group_id
        and wg.user_id = (select auth.uid())
    )
    and exists (
      select 1
      from public.saved_words sw
      where sw.id = saved_word_id
        and sw.user_id = (select auth.uid())
    )
  );

drop policy if exists "Users can read own flashcards" on public.flashcards;
create policy "Users can read own flashcards"
  on public.flashcards for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can read own flashcard reviews"
  on public.flashcard_reviews;
create policy "Users can read own flashcard reviews"
  on public.flashcard_reviews for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- PostgreSQL views are SECURITY DEFINER unless security_invoker is enabled.
-- These views must obey the caller's grants and the base-table RLS policies.
alter view public.v_videos_with_language set (security_invoker = true);
alter view public.v_user_library_details set (security_invoker = true);
alter view public.v_smart_groups set (security_invoker = true);

-- Fix mutable search paths for application-owned public functions. Trigger
-- functions are not directly callable; read-only helpers retain explicit Data
-- API access. Authority/maintenance RPCs remain service-only.
alter function public.auto_create_flashcard() set search_path = public, pg_temp;
alter function public.compute_word_count() set search_path = public, pg_temp;
alter function public.find_word_in_videos(text, character varying, integer) set search_path = public, pg_temp;
alter function public.get_due_flashcards(uuid, uuid, integer) set search_path = public, pg_temp;
alter function public.get_romanization(jsonb, character varying) set search_path = public, pg_temp;
alter function public.get_translation(jsonb, character varying, character varying) set search_path = public, pg_temp;
alter function public.refresh_video_stats() set search_path = public, pg_temp;
alter function public.search_subtitles(text, text, character varying) set search_path = public, pg_temp;
alter function public.set_updated_at() set search_path = public, pg_temp;
alter function public.sync_video_available_translations() set search_path = public, pg_temp;
alter function public.sync_word_group_count() set search_path = public, pg_temp;
alter function public.update_video_on_ai_ready() set search_path = public, pg_temp;
alter function public.update_video_on_subtitle_insert() set search_path = public, pg_temp;
alter function public.upsert_romanization(jsonb, text, text) set search_path = public, pg_temp;
alter function public.upsert_translation(jsonb, character varying, text) set search_path = public, pg_temp;
alter function public.videos_search_vector_update() set search_path = public, pg_temp;

revoke execute on function public.auto_create_flashcard() from public, anon, authenticated;
revoke execute on function public.compute_word_count() from public, anon, authenticated;
revoke execute on function public.get_due_flashcards(uuid, uuid, integer) from public, anon, authenticated;
revoke execute on function public.refresh_video_stats() from public, anon, authenticated;
revoke execute on function public.set_updated_at() from public, anon, authenticated;
revoke execute on function public.sync_video_available_translations() from public, anon, authenticated;
revoke execute on function public.sync_word_group_count() from public, anon, authenticated;
revoke execute on function public.update_video_on_ai_ready() from public, anon, authenticated;
revoke execute on function public.update_video_on_subtitle_insert() from public, anon, authenticated;
revoke execute on function public.videos_search_vector_update() from public, anon, authenticated;

revoke execute on function public.find_word_in_videos(text, character varying, integer)
  from public;
revoke execute on function public.get_romanization(jsonb, character varying)
  from public;
revoke execute on function public.get_translation(jsonb, character varying, character varying)
  from public;
revoke execute on function public.search_subtitles(text, text, character varying)
  from public;
revoke execute on function public.upsert_romanization(jsonb, text, text)
  from public;
revoke execute on function public.upsert_translation(jsonb, character varying, text)
  from public;

grant execute on function public.find_word_in_videos(text, character varying, integer)
  to anon, authenticated, service_role;
grant execute on function public.get_romanization(jsonb, character varying)
  to anon, authenticated, service_role;
grant execute on function public.get_translation(jsonb, character varying, character varying)
  to anon, authenticated, service_role;
grant execute on function public.search_subtitles(text, text, character varying)
  to anon, authenticated, service_role;
grant execute on function public.upsert_romanization(jsonb, text, text)
  to anon, authenticated, service_role;
grant execute on function public.upsert_translation(jsonb, character varying, text)
  to anon, authenticated, service_role;
grant execute on function public.get_due_flashcards(uuid, uuid, integer)
  to service_role;
grant execute on function public.refresh_video_stats()
  to service_role;

-- New objects owned by postgres start private instead of inheriting broad
-- Data API grants. Migrations must grant each future direct-client surface.
alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke execute on functions from public, anon, authenticated;
alter default privileges for role postgres in schema public
  grant all on tables to service_role;
alter default privileges for role postgres in schema public
  grant all on sequences to service_role;
alter default privileges for role postgres in schema public
  grant execute on functions to service_role;

-- ---------------------------------------------------------------------------
-- Foreign-key support indexes. Each was verified absent from the deployed
-- schema before this migration; they support current joins and FK maintenance.
-- ---------------------------------------------------------------------------

create index if not exists learning_activities_language_idx
  on public.learning_activities (language);
create index if not exists learning_activities_subtitle_id_idx
  on public.learning_activities (subtitle_id);
create index if not exists saved_words_language_idx
  on public.saved_words (language);
create index if not exists saved_words_subtitle_id_idx
  on public.saved_words (subtitle_id);
create index if not exists saved_words_video_id_idx
  on public.saved_words (video_id);
create index if not exists saved_words_vocab_id_idx
  on public.saved_words (vocab_id);
create index if not exists user_language_preferences_interface_language_idx
  on public.user_language_preferences (interface_language);
create index if not exists user_vocabulary_progress_language_idx
  on public.user_vocabulary_progress (language);
create index if not exists user_vocabulary_progress_learned_from_video_id_idx
  on public.user_vocabulary_progress (learned_from_video_id);
create index if not exists word_groups_language_idx
  on public.word_groups (language);

create index if not exists assessment_applications_attempt_id_idx
  on v3.assessment_applications (attempt_id);
create index if not exists assessment_applications_user_id_idx
  on v3.assessment_applications (user_id);
create index if not exists concept_mastery_concept_id_idx
  on v3.concept_mastery (concept_id);
create index if not exists learner_skill_states_language_code_idx
  on v3.learner_skill_states (language_code);
create index if not exists learning_objects_transcript_segment_id_idx
  on v3.learning_objects (transcript_segment_id);
create index if not exists learning_sessions_language_code_idx
  on v3.learning_sessions (language_code);
create index if not exists review_materializations_concept_id_idx
  on v3.review_materializations (concept_id);
create index if not exists review_materializations_learning_session_id_idx
  on v3.review_materializations (learning_session_id);
create index if not exists review_states_concept_id_idx
  on v3.review_states (concept_id);
create index if not exists saved_concepts_concept_id_idx
  on v3.saved_concepts (concept_id);
create index if not exists saved_concepts_source_learning_object_id_idx
  on v3.saved_concepts (source_learning_object_id);
create index if not exists session_activities_concept_id_idx
  on v3.session_activities (concept_id);
create index if not exists session_activities_learning_object_id_idx
  on v3.session_activities (learning_object_id);
create index if not exists session_activities_review_state_id_idx
  on v3.session_activities (review_state_id);
create index if not exists user_language_preferences_language_code_idx
  on v3.user_language_preferences (language_code);
create index if not exists user_language_preferences_support_language_code_idx
  on v3.user_language_preferences (support_language_code);
create index if not exists video_transcripts_language_code_idx
  on v3.video_transcripts (language_code);
create index if not exists word_groups_language_code_idx
  on v3.word_groups (language_code);
