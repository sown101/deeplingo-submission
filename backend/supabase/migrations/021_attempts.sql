-- DeepLingo v3 migration 021: raw user attempts.

create table if not exists v3.attempts (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references v3.session_activities(id) on delete cascade,
  user_id uuid not null references v3.profiles(id) on delete cascade,
  attempt_number integer not null default 1,
  status v3.attempt_status not null default 'submitted',
  response_payload jsonb not null default '{}'::jsonb,
  started_at timestamptz,
  submitted_at timestamptz,
  duration_ms integer,
  client_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint attempts_unique_number unique (activity_id, user_id, attempt_number),
  constraint attempts_attempt_number_chk check (attempt_number > 0),
  constraint attempts_duration_ms_chk check (duration_ms is null or duration_ms >= 0),
  constraint attempts_response_payload_object_chk check (jsonb_typeof(response_payload) = 'object'),
  constraint attempts_client_metadata_object_chk check (jsonb_typeof(client_metadata) = 'object')
);

comment on table v3.attempts is
  'Raw user behavior. Mastery scores are intentionally not stored here.';
