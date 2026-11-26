begin;

do $$
declare
  learner uuid := '41d7f990-3e1c-44ff-8070-14079e18f612';
  word uuid := '6efbd666-7a8c-46ef-ab15-06983e0a5443';
  answer jsonb := '{"client_event_id":"review:choice","language_code":"en","kind":"choice","outcome":"correct"}';
begin
  insert into auth.users(id) values (learner);
  insert into v3.profiles(id) values (learner) on conflict do nothing;
  insert into v3.concepts(id, language_code, type, canonical_text, normalized_text, sense_key)
    values (word, 'en', 'vocabulary', 'audit fixture', 'audit fixture', 'audit fixture');
  insert into v3.saved_concepts(user_id, concept_id, language_code, status, explicit, activated_at)
    values (learner, word, 'en', 'active', true, now());

  perform v3.submit_review_answer(learner, word, null, answer);
  if (select rung from v3.saved_concepts where user_id = learner and concept_id = word) is distinct from 1
      or not exists (select 1 from v3.target_events where user_id = learner and concept_id = word
                     and kind = 'recognition' and outcome = 'correct') then
    raise exception 'Correct choice must produce recognition evidence and R1';
  end if;

  answer := answer || '{"client_event_id":"review:cloze","kind":"cloze"}';
  perform v3.submit_review_answer(learner, word, null, answer);
  if (select rung from v3.saved_concepts where user_id = learner and concept_id = word) is distinct from 2
      or not exists (select 1 from v3.target_events where user_id = learner and concept_id = word
                     and kind = 'recall' and outcome = 'correct') then
    raise exception 'Correct cloze must produce recall evidence and R2';
  end if;
  if (v3.submit_review_answer(learner, word, null, answer)->>'status') is distinct from 'duplicate' then
    raise exception 'A retried answer must be a duplicate';
  end if;

  perform v3.submit_review_answer(learner, word, null,
    answer || '{"client_event_id":"review:wrong","outcome":"incorrect"}');
  perform v3.submit_review_answer(learner, word, null,
    answer || '{"client_event_id":"review:flashcard","kind":"flashcard"}');
  if (select count(*) from v3.target_events where user_id = learner and concept_id = word) <> 2 then
    raise exception 'Retries, misses and flashcard ratings must leave the two usage events unchanged';
  end if;

  update v3.saved_concepts set rung = 4 where user_id = learner and concept_id = word;
  perform v3.submit_review_answer(learner, word, null, answer || '{"client_event_id":"review:later-cloze"}');
  if (select rung from v3.saved_concepts where user_id = learner and concept_id = word) is distinct from 4 then
    raise exception 'Recall evidence must preserve a higher usage rung';
  end if;
end $$;

rollback;
