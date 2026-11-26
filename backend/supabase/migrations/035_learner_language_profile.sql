-- DeepLingo F2: extend the active learning-language preference with the
-- authoritative language used for explanations and semantic responses.

alter table v3.user_language_preferences
  add column if not exists support_language_code text;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'user_language_preferences_support_language_fkey'
      and conrelid = 'v3.user_language_preferences'::regclass
  ) then
    alter table v3.user_language_preferences
      add constraint user_language_preferences_support_language_fkey
      foreign key (support_language_code)
      references v3.languages(code)
      on delete restrict;
  end if;
end
$$;

comment on column v3.user_language_preferences.support_language_code is
  'Language used for explanations and semantic learner responses. Nullable until onboarding is complete; it is not necessarily the UI locale.';

comment on index v3.user_language_preferences_one_primary_idx is
  'The single primary row per user is the authoritative active learner language profile.';

-- F2 makes profile writes server-owned. Learners retain direct read access to
-- their rows for compatibility, while all mutations pass through authenticated
-- FastAPI endpoints that validate active languages and derive CurrentUser.id.
revoke insert, update, delete
  on v3.user_language_preferences
  from authenticated;

drop policy if exists "Users can manage own language preferences"
  on v3.user_language_preferences;

drop policy if exists "Users can read own language preferences"
  on v3.user_language_preferences;

create policy "Users can read own language preferences"
  on v3.user_language_preferences for select
  to authenticated
  using ((select auth.uid()) = user_id);
