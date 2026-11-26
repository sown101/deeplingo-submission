-- ADR-019 phase 1: curriculum levels, grammar points, units and targets.
--
-- Grammar points come from an inventory (HSK 3.0 GF 0025-2021 grammar syllabus for Chinese,
-- CEFR-J Grammar Profile for English; `deeplingo` only for a gap) recorded with its item
-- reference; the explanation and examples are written by DeepLingo.
--
-- Global reference content, like dictionaries: readable by everyone, written only by the
-- service role through v3.load_curriculum_level, which replaces one level atomically from a
-- reviewed repository file. Vocabulary targets name a dictionary sense (ADR-017); grammar
-- targets name a grammar point. No learner state lives here. Forward-only.

create table if not exists v3.curriculum_levels (
  id uuid primary key default gen_random_uuid(),
  language_code text not null references v3.languages(code) on delete restrict,
  framework text not null,
  level text not null,
  title text not null,
  version integer not null,
  content_hash text not null,
  source_path text not null,
  loaded_at timestamptz not null default now(),
  constraint curriculum_levels_identity unique (language_code, framework, level),
  constraint curriculum_levels_framework_check check (
    (framework = 'CEFR' and level in ('A1', 'A2', 'B1', 'B2', 'C1', 'C2'))
    or (framework = 'HSK' and level ~ '^HSK[1-9]$')),
  constraint curriculum_levels_title_check check (char_length(title) between 1 and 120),
  constraint curriculum_levels_version_check check (version >= 1),
  constraint curriculum_levels_hash_check check (content_hash ~ '^[0-9a-f]{64}$'),
  constraint curriculum_levels_source_check check (char_length(source_path) between 1 and 300)
);

comment on table v3.curriculum_levels is
  'ADR-019: one curriculum level loaded from a reviewed repository file (content_hash of that file).';

create table if not exists v3.grammar_points (
  id uuid primary key default gen_random_uuid(),
  level_id uuid not null references v3.curriculum_levels(id) on delete cascade,
  language_code text not null references v3.languages(code) on delete restrict,
  key text not null,
  title text not null,
  pattern text not null,
  explanation text not null,
  examples jsonb not null,
  inventory_source text not null,
  inventory_ref text,
  provenance text not null default 'deeplingo_authored',
  concept_id uuid references v3.concepts(id) on delete set null,
  updated_at timestamptz not null default now(),
  constraint grammar_points_key_unique unique (key),
  constraint grammar_points_key_check check (key ~ '^[a-z]{2,3}(\.[a-z0-9_]+)+$' and char_length(key) <= 80),
  constraint grammar_points_title_check check (char_length(title) between 1 and 120),
  constraint grammar_points_pattern_check check (char_length(pattern) between 1 and 160),
  constraint grammar_points_explanation_check check (char_length(explanation) between 1 and 1200),
  constraint grammar_points_examples_check check (
    jsonb_typeof(examples) = 'array' and jsonb_array_length(examples) between 1 and 6),
  constraint grammar_points_provenance_check check (provenance = 'deeplingo_authored'),
  constraint grammar_points_inventory_check check (
    (inventory_source = 'gf0025-2021' and language_code = 'zh' and inventory_ref is not null)
    or (inventory_source = 'cefrj-grammar-profile-20180315' and language_code = 'en' and inventory_ref is not null)
    or (inventory_source = 'deeplingo' and inventory_ref is null)),
  constraint grammar_points_inventory_ref_check check (inventory_ref is null or char_length(inventory_ref) between 1 and 40)
);

comment on table v3.grammar_points is
  'ADR-019: grammar points from a recorded inventory item; explanation and examples written by '
  'DeepLingo (never copied from a course); concept_id links the grammar Concept preparation selects.';

create table if not exists v3.curriculum_units (
  id uuid primary key default gen_random_uuid(),
  level_id uuid not null references v3.curriculum_levels(id) on delete cascade,
  key text not null,
  position integer not null,
  title text not null,
  topic text not null,
  can_do jsonb not null,
  updated_at timestamptz not null default now(),
  constraint curriculum_units_key_unique unique (key),
  constraint curriculum_units_position_unique unique (level_id, position) deferrable initially deferred,
  constraint curriculum_units_key_check check (key ~ '^[a-z]{2,3}\.[a-z0-9]+\.u[0-9]{2}(-[a-z0-9-]+)?$'
    and char_length(key) <= 80),
  constraint curriculum_units_position_check check (position >= 1),
  constraint curriculum_units_title_check check (char_length(title) between 1 and 120),
  constraint curriculum_units_topic_check check (char_length(topic) between 1 and 160),
  constraint curriculum_units_can_do_check check (
    jsonb_typeof(can_do) = 'array' and jsonb_array_length(can_do) between 1 and 3)
);

comment on table v3.curriculum_units is
  'ADR-019: ordered units of a curriculum level; title and can-do statements in the support language.';

create table if not exists v3.curriculum_unit_targets (
  unit_id uuid not null references v3.curriculum_units(id) on delete cascade,
  position integer not null,
  kind text not null,
  dictionary_entry_id uuid references v3.dictionary_entries(id) on delete restrict,
  sense_id text,
  grammar_point_id uuid references v3.grammar_points(id) on delete cascade,
  primary key (unit_id, position),
  constraint curriculum_unit_targets_position_check check (position >= 1),
  constraint curriculum_unit_targets_kind_check check (
    (kind = 'vocabulary' and dictionary_entry_id is not null and sense_id is not null
       and grammar_point_id is null)
    or (kind = 'grammar' and grammar_point_id is not null and dictionary_entry_id is null
       and sense_id is null)),
  constraint curriculum_unit_targets_sense_check check (sense_id is null or char_length(sense_id) between 1 and 80)
);

comment on table v3.curriculum_unit_targets is
  'ADR-019: what a unit teaches: a dictionary sense (ADR-017) or a DeepLingo grammar point.';

create index if not exists curriculum_unit_targets_entry_idx
  on v3.curriculum_unit_targets (dictionary_entry_id) where dictionary_entry_id is not null;
create index if not exists curriculum_unit_targets_grammar_idx
  on v3.curriculum_unit_targets (grammar_point_id) where grammar_point_id is not null;
create index if not exists grammar_points_level_idx on v3.grammar_points (level_id);

alter table v3.curriculum_levels enable row level security;
alter table v3.grammar_points enable row level security;
alter table v3.curriculum_units enable row level security;
alter table v3.curriculum_unit_targets enable row level security;

revoke all privileges on v3.curriculum_levels, v3.grammar_points, v3.curriculum_units,
  v3.curriculum_unit_targets from anon, authenticated;
grant select on v3.curriculum_levels, v3.grammar_points, v3.curriculum_units,
  v3.curriculum_unit_targets to anon, authenticated;
grant all privileges on v3.curriculum_levels, v3.grammar_points, v3.curriculum_units,
  v3.curriculum_unit_targets to service_role;

drop policy if exists "Public can read curriculum levels" on v3.curriculum_levels;
create policy "Public can read curriculum levels"
  on v3.curriculum_levels for select to anon, authenticated using (true);
drop policy if exists "Public can read grammar points" on v3.grammar_points;
create policy "Public can read grammar points"
  on v3.grammar_points for select to anon, authenticated using (true);
drop policy if exists "Public can read curriculum units" on v3.curriculum_units;
create policy "Public can read curriculum units"
  on v3.curriculum_units for select to anon, authenticated using (true);
drop policy if exists "Public can read curriculum unit targets" on v3.curriculum_unit_targets;
create policy "Public can read curriculum unit targets"
  on v3.curriculum_unit_targets for select to anon, authenticated using (true);

-- Replace one level from a validated payload in one transaction. Units and grammar points are
-- matched by key (stable IDs survive edits); ones missing from the payload are removed; targets
-- are rewritten. The application validates dictionary senses before calling.
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
                                   inventory_source, inventory_ref)
    values (v_level_id, v_language, v_grammar->>'key', v_grammar->>'title', v_grammar->>'pattern',
            v_grammar->>'explanation', v_grammar->'examples', v_grammar->>'source', v_grammar->>'source_ref')
    on conflict (key) do update
      set level_id = excluded.level_id, title = excluded.title, pattern = excluded.pattern,
          explanation = excluded.explanation, examples = excluded.examples,
          inventory_source = excluded.inventory_source, inventory_ref = excluded.inventory_ref, updated_at = now()
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
