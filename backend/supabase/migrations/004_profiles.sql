-- DeepLingo v3 migration 004: profiles.

create table if not exists v3.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  timezone text not null default 'UTC',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table v3.profiles is
  'Application profile for a Supabase Auth user. Does not duplicate auth secrets or language preferences.';
