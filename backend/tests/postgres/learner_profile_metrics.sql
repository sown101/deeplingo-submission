begin;

do $$
declare
  learner constant uuid := '0628c03a-bdb7-46bb-93b8-7400095b8acd';
  other constant uuid := '0628c03a-bdb7-46bb-93b8-7400095b8ace';
  english_word constant uuid := '0628c03a-bdb7-46bb-93b8-7400095b8acf';
  chinese_word constant uuid := '0628c03a-bdb7-46bb-93b8-7400095b8ad0';
  current_time_at constant timestamptz := '2026-11-23 17:15:00+00';
  summary jsonb;
begin
  insert into auth.users(id) values (learner), (other);
  insert into v3.profiles(id, timezone) values (learner, 'Asia/Ho_Chi_Minh'), (other, 'UTC')
    on conflict (id) do update set timezone = excluded.timezone;
  insert into v3.concepts(id, language_code, type, canonical_text, normalized_text, sense_key)
    values (english_word, 'en', 'vocabulary', 'audit metrics fixture', 'audit metrics fixture', 'audit metrics fixture'),
           (chinese_word, 'zh', 'vocabulary', 'audit metrics fixture', 'audit metrics fixture', 'audit metrics fixture');
  insert into v3.review_states(user_id, concept_id, language_code, review_mode, fsrs_state, due_at, lapses)
    values (learner, english_word, 'en', 'concept_to_meaning', 'review', current_time_at, 2),
           (learner, chinese_word, 'zh', 'concept_to_meaning', 'review', current_time_at, 3),
           (other, english_word, 'en', 'concept_to_meaning', 'review', current_time_at, 4);
  insert into v3.learner_activity_log(user_id, language_code, client_event_id, kind, outcome, occurred_at, detail)
    values (learner, 'en', 'audit:today', 'speaking_session', 'done', current_time_at, '{"seconds":120}'),
           (learner, 'en', 'audit:yesterday', 'speaking_session', 'done', current_time_at - interval '2 hours', '{"seconds":60}'),
           (learner, 'en', 'audit:gap', 'speaking_session', 'done', current_time_at - interval '4 days', '{"seconds":60}'),
           (learner, 'zh', 'audit:other-language', 'speaking_session', 'done', current_time_at, '{"seconds":600}'),
           (other, 'en', 'audit:other-user', 'speaking_session', 'done', current_time_at, '{"seconds":600}');

  summary := v3.learner_profile_metrics(learner, 'en', current_time_at);
  if summary is distinct from '{"cards":1,"due_now":1,"lapses":2,"streak_days":2,"minutes_last_7_days":4}'::jsonb then
    raise exception 'Profile metrics must be scoped to the learner, language and local days';
  end if;
end;
$$;

rollback;
