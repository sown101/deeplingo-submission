-- DeepLingo v3 migration 030: review transition hardening and idempotency.

alter table v3.assessments
  add constraint assessments_attempt_authoritative_unique unique (attempt_id);

alter table v3.review_events
  add column assessment_id uuid;

alter table v3.review_events
  add constraint review_events_assessment_fk
    foreign key (assessment_id) references v3.assessments(id) on delete cascade;

alter table v3.review_events
  alter column assessment_id set not null;

alter table v3.review_events
  add constraint review_events_assessment_authoritative_unique unique (assessment_id);

create index if not exists review_events_attempt_idx
  on v3.review_events (attempt_id);

comment on column v3.review_events.assessment_id is
  'Stable idempotency identity for review scheduling: one authoritative Assessment can create at most one ReviewEvent.';
