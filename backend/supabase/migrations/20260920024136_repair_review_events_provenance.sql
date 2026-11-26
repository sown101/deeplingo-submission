-- Repair an older development deployment whose review_events table predates
-- the repository's current migration 024 definition. The current assessment
-- application RPC requires this provenance column, and the leak checks are
-- part of the canonical append-only scheduling-event contract.

alter table v3.review_events
  add column if not exists provenance text not null default 'review_update_policy';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'review_events_previous_state_no_payload_leak_chk'
      and conrelid = 'v3.review_events'::regclass
  ) then
    alter table v3.review_events
      add constraint review_events_previous_state_no_payload_leak_chk check (
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
      );
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'review_events_resulting_state_no_payload_leak_chk'
      and conrelid = 'v3.review_events'::regclass
  ) then
    alter table v3.review_events
      add constraint review_events_resulting_state_no_payload_leak_chk check (
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
      );
  end if;
end
$$;

comment on column v3.review_events.provenance is
  'Trusted backend policy/adapter that produced the scheduling transition.';
