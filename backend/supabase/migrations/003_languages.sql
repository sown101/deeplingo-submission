-- DeepLingo v3 migration 003: supported languages.

create table if not exists v3.languages (
  code text primary key,
  name_en text not null,
  name_native text not null,
  script text not null,
  is_active boolean not null default true,
  display_order integer not null default 999,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint languages_code_format_chk check (code ~ '^[a-z]{2,3}(-[A-Za-z0-9]+)?$')
);

comment on table v3.languages is
  'Canonical supported languages. Per-user preferences belong in user_language_preferences.';
