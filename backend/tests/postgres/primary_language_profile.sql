begin;

do $$
declare
  first_user constant uuid := '8c2ea183-3260-4fd9-a07d-f24fd4719724';
  other_user constant uuid := '8c2ea183-3260-4fd9-a07d-f24fd4719725';
begin
  insert into auth.users(id) values (first_user), (other_user);
  insert into v3.profiles(id) values (first_user), (other_user) on conflict do nothing;

  perform v3.upsert_language_profile(first_user, 'en', 'vi', '{"declared_level":"A1","daily_new_limit":24}');
  perform v3.upsert_language_profile(other_user, 'en', 'vi', '{}');
  begin
    perform v3.upsert_language_profile(first_user, 'zh', 'unknown', '{}');
    raise exception 'Invalid language preference should have been rejected';
  exception when foreign_key_violation then
    null;
  end;
  if not exists (select from v3.user_language_preferences where user_id = first_user and language_code = 'en' and is_primary) then
    raise exception 'Failed update must preserve the primary language';
  end if;

  perform v3.upsert_language_profile(first_user, 'zh', 'vi', '{}');
  perform v3.upsert_language_profile(first_user, 'en', 'vi', '{}');
  if (select count(*) from v3.user_language_preferences where user_id = first_user and is_primary) <> 1
      or not exists (select from v3.user_language_preferences where user_id = first_user and language_code = 'en'
                     and is_primary and declared_level = 'A1' and daily_new_limit = 24)
      or not exists (select from v3.user_language_preferences where user_id = other_user and language_code = 'en' and is_primary) then
    raise exception 'Profile switches must preserve other users and omitted fields';
  end if;
end;
$$;

rollback;
