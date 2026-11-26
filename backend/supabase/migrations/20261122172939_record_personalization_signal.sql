create function v3.record_personalization_signal(
    p_user_id uuid, p_language_code text, p_kind text, p_code text, p_replace_kind boolean
) returns void
language plpgsql security invoker set search_path = '' as $$
begin
  if p_replace_kind then
    -- Two different codes of a single-value kind must replace each other in order.
    perform pg_advisory_xact_lock(hashtextextended(
      'personalization:' || p_user_id::text || ':' || p_language_code || ':' || p_kind, 0));
    delete from v3.learner_personalization_signals
      where user_id = p_user_id and language_code = p_language_code and kind = p_kind and code <> p_code;
  end if;

  insert into v3.learner_personalization_signals as signal (user_id, language_code, kind, code)
    values (p_user_id, p_language_code, p_kind, p_code)
    on conflict (user_id, language_code, kind, code) do update
      set usage_count = signal.usage_count + 1, updated_at = clock_timestamp();
end;
$$;

revoke all on function v3.record_personalization_signal(uuid, text, text, text, boolean)
  from public, anon, authenticated;
grant execute on function v3.record_personalization_signal(uuid, text, text, text, boolean) to service_role;
