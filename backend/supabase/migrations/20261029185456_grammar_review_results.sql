-- Draft only: FR-8.3 private practice results. No assessment events or FSRS writes.
create table v3.learner_grammar_review_results (
  user_id uuid not null references v3.profiles(id) on delete cascade,
  attempt_id uuid not null,
  bank_hash text not null check (bank_hash ~ '^[0-9a-f]{64}$'),
  bank_version integer not null check (bank_version > 0),
  question_id text not null check (length(question_id) between 1 and 120),
  grammar_key text not null check (length(grammar_key) between 1 and 80),
  language_code text not null references v3.languages(code),
  selected_option_id text not null check (length(selected_option_id) between 1 and 20),
  is_correct boolean not null,
  created_at timestamptz not null default now(),
  primary key (user_id, attempt_id)
);
create index learner_grammar_review_point_idx on v3.learner_grammar_review_results(user_id, grammar_key);
alter table v3.learner_grammar_review_results enable row level security;
revoke all on v3.learner_grammar_review_results from public, anon, authenticated;
grant select, insert on v3.learner_grammar_review_results to service_role;

create function v3.record_grammar_review_result(p_user_id uuid, p_result jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare stored v3.learner_grammar_review_results;
begin
  insert into v3.learner_grammar_review_results
    (user_id, attempt_id, bank_hash, bank_version, question_id, grammar_key, language_code, selected_option_id, is_correct)
  values (p_user_id, (p_result->>'attempt_id')::uuid, p_result->>'bank_hash',
    (p_result->>'bank_version')::integer, p_result->>'question_id', p_result->>'grammar_key',
    p_result->>'language_code', p_result->>'selected_option_id', (p_result->>'is_correct')::boolean)
  on conflict (user_id, attempt_id) do nothing;
  select * into strict stored from v3.learner_grammar_review_results
    where user_id = p_user_id and attempt_id = (p_result->>'attempt_id')::uuid;
  return jsonb_build_object('conflict', (to_jsonb(stored) - 'user_id' - 'created_at') <> p_result);
end;
$$;

create function v3.grammar_review_summary(p_user_id uuid)
returns table(grammar_key text, correct_count bigint, incorrect_count bigint)
language sql stable security invoker set search_path = '' as $$
  select r.grammar_key, count(*) filter (where r.is_correct), count(*) filter (where not r.is_correct)
  from v3.learner_grammar_review_results r where r.user_id = p_user_id group by r.grammar_key;
$$;
revoke all on function v3.record_grammar_review_result(uuid, jsonb) from public, anon, authenticated;
revoke all on function v3.grammar_review_summary(uuid) from public, anon, authenticated;
grant execute on function v3.record_grammar_review_result(uuid, jsonb) to service_role;
grant execute on function v3.grammar_review_summary(uuid) to service_role;
