-- L1c: mark a lexeme level that was inferred (owner-approved 2026-10-26). Forward-only and additive.
--
-- A Chinese compound the HSK list does not name (每天) takes the highest level among its characters when every
-- character has one. That is a reading aid, not a dictionary fact, so it is stored as inferred. Cached profiles
-- older than PROFILE_VERSION 3 are rebuilt by the application on next read.
--
-- Not applied to any environment by this file's author. Applying it needs the owner's approval.

alter table v3.video_lexemes add column if not exists level_derived boolean not null default false;

comment on column v3.video_lexemes.level_derived is
  'true when level_label was inferred from the characters of the word, not named by the dictionary level list.';
