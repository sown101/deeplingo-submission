-- DeepLingo v3 migration 005: per-user language preferences.

create table if not exists v3.user_language_preferences (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references v3.profiles(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  target_level text,
  learning_goal text,
  is_primary boolean not null default false,
  preferences jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_language_preferences_unique_language unique (user_id, language_code),
  constraint user_language_preferences_preferences_object_chk check (jsonb_typeof(preferences) = 'object')
);

comment on table v3.user_language_preferences is
  'User-specific learning language settings. JSONB is limited to optional preferences, not ownership or language identity.';
