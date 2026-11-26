-- FR-8.2: owner-approved draft only; applying this migration needs separate approval.
-- Shared content explanations, never learner state. All cache reads follow Library authorization.
create table v3.transcript_grammar_explanations (
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  support_language_code text not null check (char_length(support_language_code) between 2 and 16),
  version text not null check (char_length(version) between 1 and 80),
  explanation jsonb not null check (jsonb_typeof(explanation) = 'object'),
  created_at timestamptz not null default now(),
  primary key (source_hash, support_language_code, version)
);

alter table v3.transcript_grammar_explanations enable row level security;
revoke all privileges on table v3.transcript_grammar_explanations from public, anon, authenticated;
grant select, insert, update on table v3.transcript_grammar_explanations to service_role;

comment on table v3.transcript_grammar_explanations is
  'FR-8.2: unverified AI explanations cached by trusted source, selection, support language and version; no learner identifiers.';
