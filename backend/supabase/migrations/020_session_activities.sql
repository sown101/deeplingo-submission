-- DeepLingo v3 migration 020: ordered session activities.

create table if not exists v3.session_activities (
  id uuid primary key default extensions.gen_random_uuid(),
  session_id uuid not null references v3.learning_sessions(id) on delete cascade,
  concept_id uuid references v3.concepts(id) on delete set null,
  learning_object_id uuid references v3.learning_objects(id) on delete set null,
  activity_type v3.activity_type not null,
  position integer not null,
  prompt_payload jsonb not null default '{}'::jsonb,
  expected_response_payload jsonb,
  status v3.activity_status not null default 'planned',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint session_activities_unique_position unique (session_id, position),
  constraint session_activities_position_chk check (position > 0),
  constraint session_activities_prompt_payload_object_chk check (jsonb_typeof(prompt_payload) = 'object'),
  constraint session_activities_expected_response_payload_object_chk check (
    expected_response_payload is null or jsonb_typeof(expected_response_payload) = 'object'
  )
);

comment on table v3.session_activities is
  'Activity-specific prompts may use JSONB, but ownership/type/position/status remain typed columns.';
