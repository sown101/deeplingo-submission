-- 2026-11-05 (owner decision): study parts cut by the model, cached per transcript version.
-- Shared content, never learner state; reads follow Library authorization in the API.
-- Draft: applying this migration to any environment needs the owner's approval for that environment.
create table v3.transcript_parts (
  transcript_id uuid not null references v3.video_transcripts (id) on delete cascade,
  version text not null check (char_length(version) between 1 and 80),
  parts jsonb not null check (jsonb_typeof(parts) = 'array' and jsonb_array_length(parts) between 1 and 400),
  created_at timestamptz not null default now(),
  primary key (transcript_id, version)
);

alter table v3.transcript_parts enable row level security;
revoke all privileges on table v3.transcript_parts from public, anon, authenticated;
grant select, insert, update on table v3.transcript_parts to service_role;

comment on table v3.transcript_parts is
  'Study parts of a transcript cut by AI (start/end segment, title); shared content with no learner identifiers.';
