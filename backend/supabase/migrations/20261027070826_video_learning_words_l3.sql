-- L3: the learner's explicit saved-word links to their own Library videos.
-- Forward-only; applying requires environment-specific owner approval.

create table v3.learner_video_words (
  user_id uuid not null,
  library_item_id uuid not null,
  concept_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (user_id, library_item_id, concept_id),
  foreign key (library_item_id, user_id) references v3.learner_videos(id, user_id) on delete cascade,
  foreign key (user_id, concept_id) references v3.saved_concepts(user_id, concept_id) on delete cascade
);
create index learner_video_words_concept_idx on v3.learner_video_words(user_id, concept_id);
alter table v3.learner_video_words enable row level security;
revoke all on v3.learner_video_words from public, anon, authenticated;
grant select on v3.learner_video_words to authenticated;
grant all on v3.learner_video_words to service_role;
create policy "Learners read own video words" on v3.learner_video_words
  for select to authenticated using ((select auth.uid()) = user_id);
