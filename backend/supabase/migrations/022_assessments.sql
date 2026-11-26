-- DeepLingo v3 migration 022: attempt assessments.

create table if not exists v3.assessments (
  id uuid primary key default extensions.gen_random_uuid(),
  attempt_id uuid not null references v3.attempts(id) on delete cascade,
  assessor_type v3.assessment_assessor_type not null,
  meaning_score numeric(4,3),
  grammar_score numeric(4,3),
  naturalness_score numeric(4,3),
  pronunciation_score numeric(4,3),
  fluency_score numeric(4,3),
  overall_score numeric(4,3),
  feedback jsonb not null default '{}'::jsonb,
  raw_ai_diagnostics jsonb,
  assessed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint assessments_scores_chk check (
    (meaning_score is null or meaning_score between 0 and 1) and
    (grammar_score is null or grammar_score between 0 and 1) and
    (naturalness_score is null or naturalness_score between 0 and 1) and
    (pronunciation_score is null or pronunciation_score between 0 and 1) and
    (fluency_score is null or fluency_score between 0 and 1) and
    (overall_score is null or overall_score between 0 and 1)
  ),
  constraint assessments_feedback_object_chk check (jsonb_typeof(feedback) = 'object'),
  constraint assessments_raw_ai_diagnostics_object_chk check (
    raw_ai_diagnostics is null or jsonb_typeof(raw_ai_diagnostics) = 'object'
  )
);

comment on table v3.assessments is
  'Evaluation evidence only. Mastery updates are performed by backend domain services, not SQL triggers.';
