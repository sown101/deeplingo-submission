-- DeepLingo v3 migration 006: content channels.

create table if not exists v3.channels (
  id uuid primary key default extensions.gen_random_uuid(),
  source v3.content_source not null default 'youtube',
  external_channel_id text not null,
  channel_name text not null,
  channel_url text,
  description text,
  thumbnail_url text,
  subscriber_count bigint,
  category text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint channels_source_external_unique unique (source, external_channel_id),
  constraint channels_subscriber_count_chk check (subscriber_count is null or subscriber_count >= 0),
  constraint channels_metadata_object_chk check (jsonb_typeof(metadata) = 'object')
);
