create function v3.upsert_language_profile(
  p_user_id uuid, p_learning_language text, p_support_language text, p_extra jsonb
) returns setof v3.user_language_preferences
language plpgsql security invoker set search_path = '' as $$
begin
  perform pg_advisory_xact_lock(hashtextextended('language_profile:' || p_user_id::text, 0));

  update v3.user_language_preferences
     set is_primary = false, updated_at = now()
   where user_id = p_user_id and is_primary and language_code <> p_learning_language;

  return query insert into v3.user_language_preferences as preference (
    user_id, language_code, support_language_code, is_primary, declared_level, daily_new_limit
  ) values (
    p_user_id, p_learning_language, p_support_language, true,
    p_extra->>'declared_level', coalesce((p_extra->>'daily_new_limit')::smallint, 10)
  ) on conflict (user_id, language_code) do update set
    support_language_code = excluded.support_language_code,
    is_primary = true,
    declared_level = case when p_extra ? 'declared_level' then excluded.declared_level else preference.declared_level end,
    daily_new_limit = case when p_extra ? 'daily_new_limit' then excluded.daily_new_limit else preference.daily_new_limit end,
    updated_at = now()
  returning preference.*;
end;
$$;

revoke all on function v3.upsert_language_profile(uuid, text, text, jsonb) from public, anon, authenticated;
grant execute on function v3.upsert_language_profile(uuid, text, text, jsonb) to service_role;
