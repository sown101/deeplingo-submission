-- Run on a disposable local database. The two sessions need a committed fixture.
create extension if not exists dblink with schema extensions;

insert into auth.users(id) values ('72565bc3-b4e2-44b6-b58b-4878d3585fbc');
insert into v3.profiles(id) values ('72565bc3-b4e2-44b6-b58b-4878d3585fbc') on conflict do nothing;

do $$
declare
  learner uuid := '72565bc3-b4e2-44b6-b58b-4878d3585fbc';
  record_topic text := format('select v3.record_personalization_signal(%L, %L, %L, %L, false)',
                              learner, 'en', 'topic', 'food');
  conn text := format('dbname=%s', current_database());
begin
  if has_function_privilege('authenticated', 'v3.record_personalization_signal(uuid,text,text,text,boolean)',
                            'execute') then
    raise exception 'The signal RPC must be service-role only';
  end if;

  perform extensions.dblink_connect('first', conn);
  perform extensions.dblink_connect('second', conn);
  perform extensions.dblink_send_query('first', record_topic);
  perform extensions.dblink_send_query('second', record_topic);
  perform result from extensions.dblink_get_result('first') as response(result text);
  perform result from extensions.dblink_get_result('second') as response(result text);
  perform result from extensions.dblink_get_result('first') as response(result text);
  perform result from extensions.dblink_get_result('second') as response(result text);
  if (select usage_count from v3.learner_personalization_signals
      where user_id = learner and language_code = 'en' and kind = 'topic' and code = 'food') is distinct from 2 then
    raise exception 'Two concurrent first sightings must be counted';
  end if;

  perform extensions.dblink_send_query('first', record_topic);
  perform extensions.dblink_send_query('second', record_topic);
  perform result from extensions.dblink_get_result('first') as response(result text);
  perform result from extensions.dblink_get_result('second') as response(result text);
  perform result from extensions.dblink_get_result('first') as response(result text);
  perform result from extensions.dblink_get_result('second') as response(result text);
  if (select usage_count from v3.learner_personalization_signals
      where user_id = learner and language_code = 'en' and kind = 'topic' and code = 'food') is distinct from 4 then
    raise exception 'Two concurrent increments on an existing signal must both survive';
  end if;

  perform extensions.dblink_send_query('first', format(
    'select v3.record_personalization_signal(%L, %L, %L, %L, true)', learner, 'en', 'pace', 'slow'));
  perform extensions.dblink_send_query('second', format(
    'select v3.record_personalization_signal(%L, %L, %L, %L, true)', learner, 'en', 'pace', 'steady'));
  perform result from extensions.dblink_get_result('first') as response(result text);
  perform result from extensions.dblink_get_result('second') as response(result text);
  if (select count(*) from v3.learner_personalization_signals
      where user_id = learner and language_code = 'en' and kind = 'pace') <> 1 then
    raise exception 'Concurrent replacements of a single-value signal must leave one current value';
  end if;
  perform extensions.dblink_disconnect('first');
  perform extensions.dblink_disconnect('second');
end $$;

delete from auth.users where id = '72565bc3-b4e2-44b6-b58b-4878d3585fbc';
