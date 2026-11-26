-- ADR-020 phase 2: a licensed real-sentence corpus (Tatoeba, CC BY 2.0 FR) for example sentences.
--
-- Shared reference text owned by the content module, loaded offline by
-- backend/scripts/content/import_tatoeba.py (a bounded subset of short everyday sentences, not
-- the whole export). A sentence reaches a learner only as an `example_sentences` row of kind
-- `corpus`, after a structured sense check, with its author and licence shown. Service role
-- only; clients have no grant. Deleting learner test data never touches these rows.
-- Forward-only.

create extension if not exists pg_trgm;

create table if not exists v3.corpus_sentences (
  id uuid primary key default gen_random_uuid(),
  source text not null check (source in ('tatoeba')),
  source_id bigint not null,
  language_code text not null references v3.languages(code) on delete restrict,
  text text not null check (char_length(text) between 1 and 240),
  author text check (author is null or char_length(author) between 1 and 80),
  license text not null,
  -- Human translations keyed by language code, e.g. {"vi": "..."}.
  translations jsonb not null default '{}'::jsonb check (jsonb_typeof(translations) = 'object'),
  created_at timestamptz not null default now()
);

comment on table v3.corpus_sentences is
  'ADR-020 phase 2: Tatoeba sentences (CC BY 2.0 FR). Reference text only; shown to learners via '
  'example_sentences with author and licence. Written only by the offline import script.';

create unique index if not exists corpus_sentences_source_uidx
  on v3.corpus_sentences (source, source_id);
create index if not exists corpus_sentences_fts_en_idx
  on v3.corpus_sentences using gin (to_tsvector('simple', text))
  where language_code = 'en';
create index if not exists corpus_sentences_trgm_zh_idx
  on v3.corpus_sentences using gin (text gin_trgm_ops)
  where language_code = 'zh';

alter table v3.corpus_sentences enable row level security;
revoke all privileges on v3.corpus_sentences from anon, authenticated;
grant all privileges on v3.corpus_sentences to service_role;

-- Candidate sentences that contain the form: a whole-word phrase match for spaced languages and
-- a substring match for Chinese. Short sentences with a translation come first. The caller
-- still checks the form and asks for a sense check; this only narrows the search.
create or replace function v3.find_corpus_sentences(
  p_language_code text,
  p_form text,
  p_translation_language text,
  p_limit integer default 20
)
returns table (
  id uuid, source text, source_id bigint, text text, author text, license text, translation text
)
language sql
stable
security invoker
set search_path = ''
as $$
  select c.id, c.source, c.source_id, c.text, c.author, c.license,
         c.translations->>p_translation_language
  from v3.corpus_sentences c
  where c.language_code = p_language_code
    and char_length(btrim(p_form)) between 1 and 80
    and (
      (p_language_code = 'en'
        and to_tsvector('simple', c.text) @@ phraseto_tsquery('simple', p_form))
      or (p_language_code = 'zh'
        and c.text like '%' || replace(replace(replace(p_form, '\', '\\'), '%', '\%'), '_', '\_') || '%')
    )
  order by (c.translations ? p_translation_language) desc, char_length(c.text), c.source_id
  limit least(greatest(p_limit, 1), 50);
$$;

revoke all on function v3.find_corpus_sentences(text, text, text, integer)
  from public, anon, authenticated;
grant execute on function v3.find_corpus_sentences(text, text, text, integer) to service_role;
