-- ADR-019: closed-class forms of a grammar point (pronouns, 是, am/is/are ...).
--
-- The grammar selection pass keeps a use only when its span contains one listed form, so a
-- name is never taken for a pronoun. Empty for open patterns (for example the present simple).
-- Additive and forward-only; v3.load_curriculum_level is replaced to write the column.

alter table v3.grammar_points
  add column if not exists forms jsonb not null default '[]'::jsonb;

alter table v3.grammar_points
  add constraint grammar_points_forms_check check (
    jsonb_typeof(forms) = 'array' and jsonb_array_length(forms) <= 40);

create or replace function v3.load_curriculum_level(p_level jsonb)
returns jsonb language plpgsql security invoker
set search_path = '' set lock_timeout = '3s' set statement_timeout = '30s' as $$
declare
  v_level_id uuid;
  v_language text := p_level->>'language_code';
  v_unit jsonb;
  v_unit_id uuid;
  v_target jsonb;
  v_grammar jsonb;
  v_units integer := 0;
  v_targets integer := 0;
  v_grammar_count integer := 0;
begin
  if jsonb_typeof(p_level->'units') <> 'array' or jsonb_typeof(p_level->'grammar') <> 'array' then
    raise exception 'curriculum_payload_invalid' using errcode = '22023';
  end if;

  insert into v3.curriculum_levels (language_code, framework, level, title, version, content_hash, source_path)
  values (v_language, p_level->>'framework', p_level->>'level', p_level->>'title',
          (p_level->>'version')::integer, p_level->>'content_hash', p_level->>'source_path')
  on conflict (language_code, framework, level) do update
    set title = excluded.title, version = excluded.version, content_hash = excluded.content_hash,
        source_path = excluded.source_path, loaded_at = now()
  returning id into v_level_id;

  for v_grammar in select value from jsonb_array_elements(p_level->'grammar') loop
    insert into v3.grammar_points (level_id, language_code, key, title, pattern, explanation, examples,
                                   inventory_source, inventory_ref, forms)
    values (v_level_id, v_language, v_grammar->>'key', v_grammar->>'title', v_grammar->>'pattern',
            v_grammar->>'explanation', v_grammar->'examples', v_grammar->>'source', v_grammar->>'source_ref',
            coalesce(v_grammar->'forms', '[]'::jsonb))
    on conflict (key) do update
      set level_id = excluded.level_id, title = excluded.title, pattern = excluded.pattern,
          explanation = excluded.explanation, examples = excluded.examples,
          inventory_source = excluded.inventory_source, inventory_ref = excluded.inventory_ref,
          forms = excluded.forms, updated_at = now()
      where v3.grammar_points.language_code = excluded.language_code;
    if not found then
      raise exception 'grammar_key_owned_by_other_language' using errcode = '23505';
    end if;
    v_grammar_count := v_grammar_count + 1;
  end loop;

  delete from v3.curriculum_units u
  where u.level_id = v_level_id
    and u.key not in (select value->>'key' from jsonb_array_elements(p_level->'units'));

  for v_unit in select value from jsonb_array_elements(p_level->'units') loop
    insert into v3.curriculum_units (level_id, key, position, title, topic, can_do)
    values (v_level_id, v_unit->>'key', (v_unit->>'position')::integer, v_unit->>'title',
            v_unit->>'topic', v_unit->'can_do')
    on conflict (key) do update
      set position = excluded.position, title = excluded.title, topic = excluded.topic,
          can_do = excluded.can_do, updated_at = now()
      where v3.curriculum_units.level_id = excluded.level_id
    returning id into v_unit_id;
    if v_unit_id is null then
      raise exception 'unit_key_owned_by_other_level' using errcode = '23505';
    end if;
    v_units := v_units + 1;

    delete from v3.curriculum_unit_targets t where t.unit_id = v_unit_id;
    for v_target in select value from jsonb_array_elements(v_unit->'targets') loop
      insert into v3.curriculum_unit_targets (unit_id, position, kind, dictionary_entry_id, sense_id, grammar_point_id)
      values (
        v_unit_id, (v_target->>'position')::integer, v_target->>'kind',
        (v_target->>'dictionary_entry_id')::uuid, v_target->>'sense_id',
        case when v_target->>'kind' = 'grammar' then
          (select g.id from v3.grammar_points g where g.key = v_target->>'grammar_key' and g.level_id = v_level_id)
        end);
      v_targets := v_targets + 1;
    end loop;
  end loop;

  delete from v3.grammar_points g
  where g.level_id = v_level_id
    and g.key not in (select value->>'key' from jsonb_array_elements(p_level->'grammar'));

  return jsonb_build_object('level_id', v_level_id, 'units', v_units, 'targets', v_targets,
                            'grammar_points', v_grammar_count);
end;
$$;

revoke all on function v3.load_curriculum_level(jsonb) from public, anon, authenticated;
grant execute on function v3.load_curriculum_level(jsonb) to service_role;
