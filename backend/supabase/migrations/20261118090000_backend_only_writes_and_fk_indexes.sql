-- Learner tables are written by the backend only, and foreign keys that cascade have an index (audit 2026-11-18).
--
-- 1. The web reaches data through the API; nothing writes these tables with a learner's token. Their write grants
--    and "manage own" policies for `authenticated` are replaced by read-only ones (the owner still reads their rows).
-- 2. A delete of a video, a learner video, a concept, a segment or a region preparation scans every child table
--    without an index on its foreign key. The keys that point at the small `languages` table are left without one.

revoke insert, update, delete on v3.profiles, v3.saved_concepts, v3.word_groups, v3.word_group_items from authenticated;

drop policy if exists "Users can update own profile" on v3.profiles;

drop policy if exists "Users can manage own saved concepts" on v3.saved_concepts;
drop policy if exists "Users can read own saved concepts" on v3.saved_concepts;
create policy "Users can read own saved concepts" on v3.saved_concepts
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "Users can manage own word groups" on v3.word_groups;
drop policy if exists "Users can read own word groups" on v3.word_groups;
create policy "Users can read own word groups" on v3.word_groups
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "Users can manage own word group items" on v3.word_group_items;
drop policy if exists "Users can read own word group items" on v3.word_group_items;
create policy "Users can read own word group items" on v3.word_group_items
  for select to authenticated using (exists (
    select 1 from v3.word_groups wg where wg.id = word_group_items.group_id and wg.user_id = (select auth.uid())));

create index if not exists grammar_points_concept_idx on v3.grammar_points (concept_id);
create index if not exists learner_looked_up_concepts_concept_idx on v3.learner_looked_up_concepts (concept_id);
create index if not exists learner_new_video_imports_video_idx on v3.learner_new_video_imports (video_id);
create index if not exists learner_practice_events_library_item_idx on v3.learner_practice_events (library_item_id, user_id);
create index if not exists learner_region_preparation_requests_preparation_idx
  on v3.learner_region_preparation_requests (region_preparation_id);
create index if not exists learner_video_words_library_item_idx on v3.learner_video_words (library_item_id, user_id);
create index if not exists region_questions_evidence_segment_idx on v3.region_questions (evidence_segment_id);
create index if not exists speaking_sessions_library_item_idx on v3.speaking_sessions (library_item_id);
create index if not exists target_events_concept_idx on v3.target_events (concept_id);
create index if not exists video_region_preparations_start_segment_idx on v3.video_region_preparations (start_segment_id);
create index if not exists video_region_preparations_end_segment_idx on v3.video_region_preparations (end_segment_id);
create index if not exists video_region_preparations_video_idx on v3.video_region_preparations (video_id);
create index if not exists word_group_import_rows_user_idx on v3.word_group_import_rows (user_id);
