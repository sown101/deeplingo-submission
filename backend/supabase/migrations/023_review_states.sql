-- DeepLingo v3 migration 023: current review scheduling state.

create table if not exists v3.review_states (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  concept_id uuid not null references v3.concepts(id) on delete cascade,
  review_mode v3.review_mode not null,
  stability numeric(8,4) not null default 0,
  difficulty numeric(8,4) not null default 0,
  elapsed_days integer not null default 0,
  scheduled_days integer not null default 0,
  reps integer not null default 0,
  lapses integer not null default 0,
  fsrs_state v3.fsrs_state not null default 'new',
  due_at timestamptz not null default now(),
  last_reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint review_states_unique_mode unique (user_id, concept_id, review_mode),
  constraint review_states_nonnegative_chk check (
    stability >= 0 and
    difficulty between 0 and 10 and
    elapsed_days >= 0 and
    scheduled_days >= 0 and
    reps >= 0 and
    lapses >= 0
  ),
  constraint review_states_new_state_chk check (
    fsrs_state <> 'new' or (
      reps = 0 and
      lapses = 0 and
      elapsed_days = 0 and
      scheduled_days = 0 and
      last_reviewed_at is null
    )
  )
);

comment on table v3.review_states is
  'Current FSRS-compatible scheduling state. Separate from concept mastery.';

comment on column v3.review_states.review_mode is
  'Scheduling context/direction, not a mastery dimension or skill.';
comment on column v3.review_states.stability is
  'py-fsrs stability. Zero means no mature FSRS card state has been produced yet.';
comment on column v3.review_states.difficulty is
  'py-fsrs difficulty. Zero means no mature FSRS card state has been produced yet; mature values are bounded to 0..10.';
comment on column v3.review_states.fsrs_state is
  'Scheduling state. This is distinct from v3.mastery_state.';
comment on column v3.review_states.due_at is
  'Next due timestamp for scheduling queries. Initial states are due at server initialization time.';
