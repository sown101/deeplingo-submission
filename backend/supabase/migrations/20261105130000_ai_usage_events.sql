-- 2026-11-05 (owner decision): AI cost ledger, so real cost can be measured per feature, model and day.
-- Token counts only: no prompt, answer, learner, Library item or scope id.
-- Draft: applying this migration to any environment needs the owner's approval for that environment.
create table v3.ai_usage_events (
  id bigint generated always as identity primary key,
  occurred_at timestamptz not null default now(),
  provider text not null check (char_length(provider) between 1 and 40),
  model text not null check (char_length(model) between 1 and 80),
  response_model text not null check (char_length(response_model) between 1 and 80),
  feature text not null check (char_length(feature) between 1 and 60),
  prompt_tokens integer not null check (prompt_tokens >= 0),
  completion_tokens integer not null check (completion_tokens >= 0),
  reasoning_tokens integer not null default 0 check (reasoning_tokens >= 0)
);

create index ai_usage_events_occurred_at_idx on v3.ai_usage_events (occurred_at);

alter table v3.ai_usage_events enable row level security;
revoke all privileges on table v3.ai_usage_events from public, anon, authenticated;
grant select, insert on table v3.ai_usage_events to service_role;

comment on table v3.ai_usage_events is
  'AI cost ledger: provider, model, feature and token counts per structured model call; no learner data.';
