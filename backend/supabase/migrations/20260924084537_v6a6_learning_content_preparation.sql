-- Learning preparation is independent of playback/transcript readiness.
-- Existing rows intentionally start at not_started; no implicit backfill runs.
alter table v3.videos
  add column if not exists learning_status text not null default 'not_started',
  add column if not exists learning_object_count integer not null default 0,
  add column if not exists learning_prepared_language_code text,
  add column if not exists learning_preparation_version text,
  add column if not exists learning_failure_code text,
  add column if not exists learning_retryable boolean not null default false,
  add column if not exists learning_started_at timestamptz,
  add column if not exists learning_completed_at timestamptz;

alter table v3.videos
  add constraint videos_learning_status_check
  check (learning_status in ('not_started', 'processing', 'ready', 'no_content', 'failed'));

alter table v3.videos
  add constraint videos_learning_object_count_check
  check (learning_object_count >= 0);
