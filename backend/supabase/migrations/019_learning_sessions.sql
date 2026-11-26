-- DeepLingo v3 migration 019: learning sessions.

create table if not exists v3.learning_sessions (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  type v3.learning_session_type not null,
  status v3.learning_session_status not null default 'planned',
  goal jsonb not null default '{}'::jsonb,
  time_budget_seconds integer,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint learning_sessions_time_budget_chk check (time_budget_seconds is null or time_budget_seconds > 0),
  constraint learning_sessions_goal_object_chk check (jsonb_typeof(goal) = 'object')
);
