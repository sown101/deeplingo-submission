-- DeepLingo 5L-4: make Concept persistence identity semantic-sense aware.
-- Existing IDs and all downstream foreign keys remain stable.

alter table v3.concepts
  add column if not exists sense_key text;

-- Historical rows may predate any stable source-language semantic label.
-- A UUID-derived legacy discriminator preserves every row without inventing,
-- merging, or reassigning semantic history. New application writes never use
-- this fallback.
update v3.concepts
set
  sense_key = 'legacy:' || id::text,
  metadata = metadata || jsonb_build_object(
    'sense_identity_version', 'sense-key-v1',
    'sense_key_provenance', 'legacy_uuid_backfill'
  )
where sense_key is null or length(btrim(sense_key)) = 0;

do $$
declare
  v_collision_count integer;
begin
  select count(*)
  into v_collision_count
  from (
    select language_code, type, normalized_text, sense_key
    from v3.concepts
    group by language_code, type, normalized_text, sense_key
    having count(*) > 1
  ) collisions;

  if v_collision_count > 0 then
    raise exception 'concept_sense_identity_collision_count:%', v_collision_count;
  end if;
end
$$;

alter table v3.concepts
  drop constraint if exists concepts_unique_normalized;

alter table v3.concepts
  alter column sense_key set not null,
  add constraint concepts_sense_key_not_blank_chk
    check (length(btrim(sense_key)) > 0),
  add constraint concepts_sense_key_length_chk
    check (char_length(sense_key) <= 500),
  add constraint concepts_unique_semantic_identity
    unique (language_code, type, normalized_text, sense_key);

comment on column v3.concepts.sense_key is
  'Server-normalized source-language semantic discriminator. Learner-, support-language-, and occurrence-independent.';

comment on constraint concepts_unique_semantic_identity on v3.concepts is
  'One reusable Concept per language, type, normalized lexical form, and semantic sense.';
