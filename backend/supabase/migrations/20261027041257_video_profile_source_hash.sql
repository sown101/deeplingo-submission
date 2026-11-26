-- Forward-only: bind each lexical profile to the exact transcript text and timing it describes.
-- Nullable for existing caches; they are rebuilt lazily on the next permitted profile build.
-- Applying requires the owner's approval for the named environment.

alter table v3.video_lexical_profiles
  add column source_hash text,
  add constraint video_lexical_profiles_source_hash_check
    check (source_hash is null or source_hash ~ '^[0-9a-f]{64}$');

comment on column v3.video_lexical_profiles.source_hash is
  'SHA-256 of ordered [start_ms,end_ms,text] segments; no transcript text is stored here.';
