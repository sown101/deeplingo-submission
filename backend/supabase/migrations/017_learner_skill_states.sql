-- DeepLingo v3 migration 017: learner skill states.

create table if not exists v3.learner_skill_states (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  skill v3.skill_type not null,
  score numeric(4,3) not null default 0,
  confidence numeric(4,3) not null default 0,
  sample_count integer not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, language_code, skill),
  constraint learner_skill_states_score_chk check (score between 0 and 1),
  constraint learner_skill_states_confidence_chk check (confidence between 0 and 1),
  constraint learner_skill_states_sample_count_chk check (sample_count >= 0)
);
