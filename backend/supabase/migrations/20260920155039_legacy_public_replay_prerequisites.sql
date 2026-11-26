-- The next historical migration hardens both v3 and the public schema it inherited.
-- Supply empty prerequisites for a clean install. The historical 20261116093000 migration
-- removes them. Existing legacy databases already have the real objects.
do $$
begin
  if to_regclass('public.language_config') is not null
      or to_regclass('v3.learner_activity_log') is not null then
    return;
  end if;

  create table public.language_config (is_active boolean);
  create table public.channels (id uuid);
  create table public.videos (id uuid);
  create table public.subtitles (id uuid);
  create table public.vocabulary_master (id uuid);
  create table public.user_library (user_id uuid);
  create table public.user_language_preferences (user_id uuid, interface_language text);
  create table public.user_vocabulary_progress (user_id uuid, language text, learned_from_video_id uuid);
  create table public.learning_activities (user_id uuid, language text, subtitle_id uuid);
  create table public.saved_words (id uuid, user_id uuid, language text, subtitle_id uuid, video_id uuid, vocab_id uuid);
  create table public.word_groups (id uuid, user_id uuid, language text);
  create table public.word_group_members (group_id uuid, saved_word_id uuid);
  create table public.flashcards (user_id uuid);
  create table public.flashcard_reviews (user_id uuid);

  create materialized view public.mv_video_stats as select id from public.videos with no data;
  create view public.v_videos_with_language as select id from public.videos;
  create view public.v_user_library_details as select user_id from public.user_library;
  create view public.v_smart_groups as select id from public.word_groups;

  create function public.auto_create_flashcard() returns void language plpgsql as 'begin return; end;';
  create function public.compute_word_count() returns void language plpgsql as 'begin return; end;';
  create function public.find_word_in_videos(text, varchar, integer) returns void language plpgsql as 'begin return; end;';
  create function public.get_due_flashcards(uuid, uuid, integer) returns void language plpgsql as 'begin return; end;';
  create function public.get_romanization(jsonb, varchar) returns void language plpgsql as 'begin return; end;';
  create function public.get_translation(jsonb, varchar, varchar) returns void language plpgsql as 'begin return; end;';
  create function public.refresh_video_stats() returns void language plpgsql as 'begin return; end;';
  create function public.search_subtitles(text, text, varchar) returns void language plpgsql as 'begin return; end;';
  create function public.set_updated_at() returns void language plpgsql as 'begin return; end;';
  create function public.sync_video_available_translations() returns void language plpgsql as 'begin return; end;';
  create function public.sync_word_group_count() returns void language plpgsql as 'begin return; end;';
  create function public.update_video_on_ai_ready() returns void language plpgsql as 'begin return; end;';
  create function public.update_video_on_subtitle_insert() returns void language plpgsql as 'begin return; end;';
  create function public.upsert_romanization(jsonb, text, text) returns void language plpgsql as 'begin return; end;';
  create function public.upsert_translation(jsonb, varchar, text) returns void language plpgsql as 'begin return; end;';
  create function public.videos_search_vector_update() returns void language plpgsql as 'begin return; end;';
end $$;
