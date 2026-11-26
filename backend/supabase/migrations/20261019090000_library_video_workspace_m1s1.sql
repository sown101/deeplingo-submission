-- M1 S1: where the learner is in each Library video (watch position and the study region).
--
-- One row per Library item (v3.learner_videos), owned by the same learner: the composite
-- foreign key keeps user_id equal to the Library item's owner, and deleting the Library item
-- or the profile deletes the row. The region is a segment range of one transcript version;
-- its columns carry no foreign keys because the server revalidates the range against the
-- current original transcript on every read and write (a stale range reads as no region).
-- Watch position is presentation state: not an Attempt, Evidence, mastery or ReviewState.
-- Learners read their own rows; writes go through authenticated FastAPI routes (service
-- role). Forward-only.

do $$ begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'v3.learner_videos'::regclass and conname = 'learner_videos_id_user_unique'
  ) then
    alter table v3.learner_videos
      add constraint learner_videos_id_user_unique unique (id, user_id);
  end if;
end $$;

create table if not exists v3.learner_video_workspaces (
  library_item_id uuid primary key,
  user_id uuid not null references v3.profiles(id) on delete cascade,
  position_ms integer check (position_ms between 0 and 86400000),
  region_transcript_id uuid,
  region_start_segment_id uuid,
  region_end_segment_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint learner_video_workspaces_library_item_fkey
    foreign key (library_item_id, user_id)
    references v3.learner_videos (id, user_id) on delete cascade,
  constraint learner_video_workspaces_region_complete check (
    (region_transcript_id is null and region_start_segment_id is null and region_end_segment_id is null)
    or (region_transcript_id is not null and region_start_segment_id is not null
        and region_end_segment_id is not null)
  )
);

comment on table v3.learner_video_workspaces is
  'M1 S1: per-Library-item watch position and study region (segment range of one transcript '
  'version). Server-written presentation state; not Evidence, mastery or ReviewState.';

create index if not exists learner_video_workspaces_user_idx
  on v3.learner_video_workspaces (user_id, updated_at desc);

alter table v3.learner_video_workspaces enable row level security;
revoke all privileges on v3.learner_video_workspaces from anon, authenticated;
grant select on v3.learner_video_workspaces to authenticated;
grant all privileges on v3.learner_video_workspaces to service_role;

drop policy if exists "Users can read own video workspaces" on v3.learner_video_workspaces;
create policy "Users can read own video workspaces"
  on v3.learner_video_workspaces for select
  to authenticated
  using ((select auth.uid()) = user_id);
