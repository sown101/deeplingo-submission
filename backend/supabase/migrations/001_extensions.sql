-- DeepLingo v3 migration 001: extensions and schema namespace.
-- v3 lives in its own schema so legacy public tables remain untouched.

create schema if not exists extensions;

create extension if not exists pgcrypto with schema extensions;

create schema if not exists v3;

comment on schema v3 is
  'DeepLingo v3 adaptive learning schema. PostgreSQL is the source of truth; legacy public tables are left untouched.';
