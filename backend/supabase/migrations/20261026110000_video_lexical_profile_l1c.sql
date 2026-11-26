-- L1c: the cached word profile of a video transcript (owner-approved plan of 2026-10-26). Forward-only and
-- additive.
--
-- The profile is derived data: how many word tokens a transcript has and how often each dictionary word
-- (lemma) occurs, with the word's level label from the dictionary. It is built by the server from the
-- stored segments and the dictionary, never from client input, and holds nothing about any learner.
-- Personal coverage ("how much of this video do I know") is computed on request from these rows plus the
-- learner's own words; it is not stored.
--
-- Not applied to any environment by this file's author. Applying it needs the owner's approval.

create table if not exists v3.video_lexical_profiles (
  transcript_id uuid primary key references v3.video_transcripts(id) on delete cascade,
  language_code text not null,
  profile_version integer not null,
  token_count integer not null,
  proper_noun_count integer not null default 0,
  speech_ms integer not null,
  built_at timestamptz not null default now(),
  constraint video_lexical_profiles_counts_check
    check (token_count >= 0 and proper_noun_count >= 0 and speech_ms >= 0)
);

comment on table v3.video_lexical_profiles is
  'Cache of a transcript word profile (token count, speaking time). Written last, so a row means its lexemes are complete.';

create table if not exists v3.video_lexemes (
  transcript_id uuid not null references v3.video_transcripts(id) on delete cascade,
  lexeme text not null,
  level_label text,
  matched boolean not null,
  occurrences integer not null,
  primary key (transcript_id, lexeme),
  constraint video_lexemes_lexeme_check check (length(btrim(lexeme)) between 1 and 120),
  constraint video_lexemes_occurrences_check check (occurrences > 0)
);

comment on table v3.video_lexemes is
  'Dictionary words (lemmas) of a transcript with how often they occur. matched=false: the form was not found in the dictionary.';

alter table v3.video_lexical_profiles enable row level security;
alter table v3.video_lexemes enable row level security;
revoke all privileges on v3.video_lexical_profiles from anon, authenticated;
revoke all privileges on v3.video_lexemes from anon, authenticated;
grant all privileges on v3.video_lexical_profiles to service_role;
grant all privileges on v3.video_lexemes to service_role;
