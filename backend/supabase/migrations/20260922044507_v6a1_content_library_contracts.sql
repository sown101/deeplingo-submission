-- DeepLingo 6A-1: learner Library membership and safe global processing state.

-- Processing is global because one completed ingestion benefits every learner
-- associated with the same (source, external_video_id) Video.
alter type v3.processing_status add value if not exists 'processing' after 'pending';

alter table v3.videos
  add column if not exists processing_error_code text,
  add column if not exists processing_retryable boolean not null default false,
  add column if not exists processing_started_at timestamptz,
  add column if not exists processing_completed_at timestamptz;

alter table v3.videos
  drop constraint if exists videos_processing_error_code_chk,
  add constraint videos_processing_error_code_chk check (
    processing_error_code is null or processing_error_code in (
      'invalid_video_url',
      'video_unavailable',
      'transcript_unavailable',
      'unsupported_content',
      'processing_failed'
    )
  );

-- Historical exception strings are not part of the Product V1 contract and
-- must not remain persisted as learner-visible failure information.
update v3.videos
set
  processing_error_code = case
    when processing_status = 'failed' then 'processing_failed'
    else null
  end,
  processing_retryable = (processing_status = 'failed'),
  processing_error = null;

comment on column v3.videos.processing_error is
  'Deprecated internal field. V3 processing must not persist raw exception strings here.';
comment on column v3.videos.processing_error_code is
  'Stable server-owned Product V1 failure code; never contains provider diagnostics.';
comment on column v3.videos.processing_retryable is
  'Whether the server permits the failed global Video ingestion to be retried.';

create table if not exists v3.learner_videos (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  video_id uuid not null references v3.videos(id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint learner_videos_unique_membership unique (user_id, video_id)
);

comment on table v3.learner_videos is
  'Idempotent learner Library membership for globally deduplicated Videos. Writes are server-owned.';

create index if not exists learner_videos_user_recent_idx
  on v3.learner_videos (user_id, created_at desc);
create index if not exists learner_videos_video_id_idx
  on v3.learner_videos (video_id);
create index if not exists videos_processing_status_updated_idx
  on v3.videos (processing_status, updated_at);

alter table v3.learner_videos enable row level security;

revoke all privileges on v3.learner_videos from anon, authenticated;
grant select on v3.learner_videos to authenticated;
grant all privileges on v3.learner_videos to service_role;

drop policy if exists "Users can read own learner videos" on v3.learner_videos;
create policy "Users can read own learner videos"
  on v3.learner_videos for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- FastAPI and workers are the sole writers. RLS remains defense in depth for
-- direct authenticated reads; no learner INSERT/UPDATE/DELETE policy exists.
revoke insert, update, delete on v3.learner_videos from authenticated;
