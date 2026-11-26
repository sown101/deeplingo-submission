-- Draft only. Explicit confirmation adds owned saved words; proposals never call this RPC.
create function v3.apply_notebook_topic_proposal(
  p_user_id uuid, p_language_code text, p_name text, p_concept_ids uuid[]
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  target_group uuid;
  target_saved uuid[];
  cleaned text := regexp_replace(btrim(p_name), '\s+', ' ', 'g');
  existing_count integer := 0;
  pending_count integer := 0;
  new_count integer;
  added integer;
begin
  if cleaned is null or length(cleaned) not between 1 and 60
    or coalesce(cardinality(p_concept_ids), 0) not between 1 and 50
    or (select count(distinct x) from unnest(p_concept_ids) x) <> cardinality(p_concept_ids) then
    return jsonb_build_object('error', 'invalid_topic_selection');
  end if;
  perform 1 from v3.profiles where id = p_user_id for update;
  if not found then return jsonb_build_object('error', 'profile_not_found'); end if;
  perform s.id from v3.saved_concepts s join v3.concepts c on c.id = s.concept_id
    where s.user_id = p_user_id and s.concept_id = any(p_concept_ids)
      and c.language_code = p_language_code and c.type in ('vocabulary', 'expression')
      and (s.language_code is null or s.language_code = p_language_code) for share of s, c;
  select array_agg(s.id) into target_saved
    from v3.saved_concepts s join v3.concepts c on c.id = s.concept_id
    where s.user_id = p_user_id and s.concept_id = any(p_concept_ids)
      and c.language_code = p_language_code and c.type in ('vocabulary', 'expression')
      and (s.language_code is null or s.language_code = p_language_code);
  if coalesce(cardinality(target_saved), 0) <> cardinality(p_concept_ids) then
    return jsonb_build_object('error', 'saved_words_not_found');
  end if;
  select id into target_group from v3.word_groups
    where user_id = p_user_id and language_code = p_language_code and lower(name) = lower(cleaned) for update;
  if target_group is null then
    if (select count(*) from v3.word_groups where user_id = p_user_id) >= 50 then
      return jsonb_build_object('error', 'notebook_limit');
    end if;
    new_count := cardinality(target_saved);
  else
    select count(*) into existing_count from v3.word_group_items where group_id = target_group;
    select count(*) into pending_count from v3.word_group_import_rows where group_id = target_group;
    select count(*) into new_count from unnest(target_saved) x
      where not exists (select 1 from v3.word_group_items i where i.group_id = target_group and i.saved_concept_id = x);
  end if;
  if existing_count + pending_count + new_count > 500 then
    return jsonb_build_object('error', 'notebook_full');
  end if;
  if target_group is null then
    insert into v3.word_groups(user_id, language_code, name) values(p_user_id, p_language_code, cleaned)
      on conflict (user_id, language_code, lower(name)) do nothing returning id into target_group;
    if target_group is null then
      -- A legacy list creator can race without taking the profile lock. Roll back this call for a safe retry.
      raise exception 'notebook changed; retry confirmation' using errcode = '40001';
    end if;
  end if;
  insert into v3.word_group_items(group_id, saved_concept_id)
    select target_group, x from unnest(target_saved) x on conflict do nothing;
  get diagnostics added = row_count;
  return jsonb_build_object('group_id', target_group, 'name', cleaned, 'language_code', p_language_code,
    'added_count', added, 'total_count', existing_count + added);
end;
$$;
revoke all on function v3.apply_notebook_topic_proposal(uuid, text, text, uuid[]) from public, anon, authenticated;
grant execute on function v3.apply_notebook_topic_proposal(uuid, text, text, uuid[]) to service_role;
