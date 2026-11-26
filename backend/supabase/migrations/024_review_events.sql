-- DeepLingo v3 migration 024: append-only review events.

create table if not exists v3.review_events (
  id uuid primary key default extensions.gen_random_uuid(),
  review_state_id uuid not null references v3.review_states(id) on delete cascade,
  attempt_id uuid references v3.attempts(id) on delete set null,
  review_mode v3.review_mode not null,
  rating integer not null,
  provenance text not null default 'review_update_policy',
  previous_scheduling_state jsonb not null,
  resulting_scheduling_state jsonb not null,
  reviewed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint review_events_rating_chk check (rating between 1 and 4),
  constraint review_events_previous_state_object_chk check (jsonb_typeof(previous_scheduling_state) = 'object'),
  constraint review_events_resulting_state_object_chk check (jsonb_typeof(resulting_scheduling_state) = 'object'),
  constraint review_events_previous_state_no_payload_leak_chk check (
    not previous_scheduling_state ?| array[
      'answer',
      'answers',
      'expected_answer',
      'expected_response',
      'prompt',
      'prompts',
      'raw_ai_diagnostics',
      'model_metadata',
      'llm',
      'response_payload'
    ]
  ),
  constraint review_events_resulting_state_no_payload_leak_chk check (
    not resulting_scheduling_state ?| array[
      'answer',
      'answers',
      'expected_answer',
      'expected_response',
      'prompt',
      'prompts',
      'raw_ai_diagnostics',
      'model_metadata',
      'llm',
      'response_payload'
    ]
  )
);

comment on table v3.review_events is
  'Immutable historical review log. It is not the current review state.';

comment on column v3.review_events.rating is
  'FSRS review rating value: 1 again, 2 hard, 3 good, 4 easy. Mapping from assessments is deferred.';
comment on column v3.review_events.provenance is
  'Trusted backend policy/adapter that produced the scheduling transition.';
comment on column v3.review_events.previous_scheduling_state is
  'Append-only scheduling snapshot before a transition. Not an attempt, assessment, answer, prompt, or mastery record.';
comment on column v3.review_events.resulting_scheduling_state is
  'Append-only scheduling snapshot after a transition. Not an attempt, assessment, answer, prompt, or mastery record.';
