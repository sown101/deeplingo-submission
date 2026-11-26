-- DeepLingo v3 migration 007: videos.

create table if not exists v3.videos (
  id uuid primary key default extensions.gen_random_uuid(),
  source v3.content_source not null default 'youtube',
  external_video_id text not null,
  channel_id uuid references v3.channels(id) on delete set null,
  original_language_code text not null references v3.languages(code) on delete restrict,
  title text not null,
  description text,
  thumbnail_url text,
  duration_ms integer,
  published_at timestamptz,
  processing_status v3.processing_status not null default 'pending',
  processing_error text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint videos_source_external_unique unique (source, external_video_id),
  constraint videos_duration_ms_chk check (duration_ms is null or duration_ms >= 0),
  constraint videos_metadata_object_chk check (jsonb_typeof(metadata) = 'object')
);

comment on table v3.videos is
  'Video metadata and processing state. Derived booleans such as has_transcript are intentionally not stored.';
