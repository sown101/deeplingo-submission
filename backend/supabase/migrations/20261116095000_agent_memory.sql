-- DRAFT. Not applied to any environment. Applying it needs the owner's approval for that environment. Forward-only.
--
-- Agent v2 phase 3 (PRD 8.12 point 3, docs/architecture/TARGET_DESIGN.md section 7): the agent remembers across
-- conversations: the learner's goals, interests, mistakes they keep making and what the agent promised to do next
-- time. One short free-text sentence per row, written by the agent through the backend only. The learner sees every
-- row in their Profile, can delete one or all, and gets them in the data export. Rows cascade with the account.
--   * language_code null = the row applies to every language the learner studies.
--   * The backend keeps at most 40 rows per learner (the oldest one goes first); there is no uniqueness on text.
-- Backend-only: row security on, no grant to anon or authenticated, service role only.

create table if not exists v3.learner_agent_memory (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text references v3.languages(code) on delete restrict,
  kind text not null,
  text text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint learner_agent_memory_kind_check check (kind in ('goal', 'interest', 'error', 'follow_up')),
  constraint learner_agent_memory_text_check check (char_length(text) between 1 and 200)
);

comment on table v3.learner_agent_memory is
  'Agent v2 phase 3: what the agent remembers about a learner across conversations (free text the learner said, one short sentence per row). Read, exported and deleted by the learner through the backend only.';

create index if not exists learner_agent_memory_recent_idx
  on v3.learner_agent_memory (user_id, created_at desc);

alter table v3.learner_agent_memory enable row level security;
revoke all privileges on v3.learner_agent_memory from public, anon, authenticated;
grant all privileges on v3.learner_agent_memory to service_role;
