-- DeepLingo v3 migration 008: transcript tracks.

create table if not exists v3.video_transcripts (
  id uuid primary key default extensions.gen_random_uuid(),
  video_id uuid not null references v3.videos(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  source v3.content_source not null default 'caption_track',
  is_original boolean not null default false,
  provider_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint video_transcripts_unique_track unique (video_id, language_code, source),
  constraint video_transcripts_provider_metadata_object_chk check (jsonb_typeof(provider_metadata) = 'object')
);
