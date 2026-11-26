-- DeepLingo v3 migration 029: grants and row-level security.

grant usage on schema v3 to anon, authenticated, service_role;

grant select on
  v3.languages,
  v3.romanization_systems,
  v3.channels,
  v3.videos,
  v3.video_transcripts,
  v3.transcript_segments,
  v3.segment_translations,
  v3.segment_romanizations,
  v3.dictionary_entries,
  v3.concepts,
  v3.concept_dictionary_links,
  v3.learning_objects
to anon, authenticated;

grant select, insert, update, delete on
  v3.profiles,
  v3.user_language_preferences,
  v3.learner_skill_states,
  v3.concept_mastery,
  v3.learning_sessions,
  v3.session_activities,
  v3.attempts,
  v3.assessments,
  v3.saved_concepts,
  v3.word_groups,
  v3.word_group_items
to authenticated;

grant select on
  v3.review_states,
  v3.review_events
to authenticated;

grant all privileges on all tables in schema v3 to service_role;

alter table v3.languages enable row level security;
alter table v3.romanization_systems enable row level security;
alter table v3.channels enable row level security;
alter table v3.videos enable row level security;
alter table v3.video_transcripts enable row level security;
alter table v3.transcript_segments enable row level security;
alter table v3.segment_translations enable row level security;
alter table v3.segment_romanizations enable row level security;
alter table v3.dictionary_entries enable row level security;
alter table v3.concepts enable row level security;
alter table v3.concept_dictionary_links enable row level security;
alter table v3.learning_objects enable row level security;
alter table v3.profiles enable row level security;
alter table v3.user_language_preferences enable row level security;
alter table v3.learner_skill_states enable row level security;
alter table v3.concept_mastery enable row level security;
alter table v3.learning_sessions enable row level security;
alter table v3.session_activities enable row level security;
alter table v3.attempts enable row level security;
alter table v3.assessments enable row level security;
alter table v3.review_states enable row level security;
alter table v3.review_events enable row level security;
alter table v3.saved_concepts enable row level security;
alter table v3.word_groups enable row level security;
alter table v3.word_group_items enable row level security;

create policy "Public can read active languages"
  on v3.languages for select
  to anon, authenticated
  using (is_active);

create policy "Public can read active romanization systems"
  on v3.romanization_systems for select
  to anon, authenticated
  using (is_active);

create policy "Public can read channels"
  on v3.channels for select
  to anon, authenticated
  using (true);

create policy "Public can read videos"
  on v3.videos for select
  to anon, authenticated
  using (true);

create policy "Public can read transcripts"
  on v3.video_transcripts for select
  to anon, authenticated
  using (true);

create policy "Public can read transcript segments"
  on v3.transcript_segments for select
  to anon, authenticated
  using (true);

create policy "Public can read segment translations"
  on v3.segment_translations for select
  to anon, authenticated
  using (true);

create policy "Public can read segment romanizations"
  on v3.segment_romanizations for select
  to anon, authenticated
  using (true);

create policy "Public can read dictionary entries"
  on v3.dictionary_entries for select
  to anon, authenticated
  using (true);

create policy "Public can read concepts"
  on v3.concepts for select
  to anon, authenticated
  using (true);

create policy "Public can read concept dictionary links"
  on v3.concept_dictionary_links for select
  to anon, authenticated
  using (true);

create policy "Public can read verified learning objects"
  on v3.learning_objects for select
  to anon, authenticated
  using (extraction_status = 'verified');

create policy "Users can read own profile"
  on v3.profiles for select
  to authenticated
  using ((select auth.uid()) = id);

create policy "Users can insert own profile"
  on v3.profiles for insert
  to authenticated
  with check ((select auth.uid()) = id);

create policy "Users can update own profile"
  on v3.profiles for update
  to authenticated
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);

create policy "Users can delete own profile"
  on v3.profiles for delete
  to authenticated
  using ((select auth.uid()) = id);

create policy "Users can manage own language preferences"
  on v3.user_language_preferences for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "Users can manage own learner skill states"
  on v3.learner_skill_states for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "Users can read own concept mastery"
  on v3.concept_mastery for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "Users can read own learning sessions"
  on v3.learning_sessions for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "Users can create own learning sessions"
  on v3.learning_sessions for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "Users can update own learning sessions"
  on v3.learning_sessions for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "Users can read own session activities"
  on v3.session_activities for select
  to authenticated
  using (
    exists (
      select 1 from v3.learning_sessions s
      where s.id = session_id and s.user_id = (select auth.uid())
    )
  );

create policy "Users can create own session activities"
  on v3.session_activities for insert
  to authenticated
  with check (
    exists (
      select 1 from v3.learning_sessions s
      where s.id = session_id and s.user_id = (select auth.uid())
    )
  );

create policy "Users can update own session activities"
  on v3.session_activities for update
  to authenticated
  using (
    exists (
      select 1 from v3.learning_sessions s
      where s.id = session_id and s.user_id = (select auth.uid())
    )
  )
  with check (
    exists (
      select 1 from v3.learning_sessions s
      where s.id = session_id and s.user_id = (select auth.uid())
    )
  );

create policy "Users can read own attempts"
  on v3.attempts for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "Users can insert own attempts"
  on v3.attempts for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "Users can update own unsubmitted attempts"
  on v3.attempts for update
  to authenticated
  using ((select auth.uid()) = user_id and submitted_at is null)
  with check ((select auth.uid()) = user_id);

create policy "Users can read assessments for own attempts"
  on v3.assessments for select
  to authenticated
  using (
    exists (
      select 1 from v3.attempts a
      where a.id = attempt_id and a.user_id = (select auth.uid())
    )
  );

create policy "Users can read own review states"
  on v3.review_states for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- ReviewState writes are intentionally service-owned in 5G-9A.
-- There is no authenticated insert/update/delete policy.

create policy "Users can read own review events"
  on v3.review_events for select
  to authenticated
  using (
    exists (
      select 1 from v3.review_states rs
      where rs.id = review_state_id and rs.user_id = (select auth.uid())
    )
  );

-- ReviewEvent writes are intentionally service-owned and append-only in 5G-9A.
-- There is no authenticated insert/update/delete policy.

create policy "Users can manage own saved concepts"
  on v3.saved_concepts for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "Users can manage own word groups"
  on v3.word_groups for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "Users can manage own word group items"
  on v3.word_group_items for all
  to authenticated
  using (
    exists (
      select 1 from v3.word_groups wg
      where wg.id = group_id and wg.user_id = (select auth.uid())
    )
  )
  with check (
    exists (
      select 1 from v3.word_groups wg
      where wg.id = group_id and wg.user_id = (select auth.uid())
    )
    and exists (
      select 1 from v3.saved_concepts sc
      where sc.id = saved_concept_id and sc.user_id = (select auth.uid())
    )
  );
