-- DeepLingo v3 migration 026: user word/concept groups.

create table if not exists v3.word_groups (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text references v3.languages(code) on delete restrict,
  name text not null,
  color text,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint word_groups_name_not_blank_chk check (length(btrim(name)) > 0)
);
