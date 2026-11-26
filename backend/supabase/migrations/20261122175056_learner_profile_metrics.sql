create function v3.learner_profile_metrics(p_user_id uuid, p_language_code text, p_now timestamptz default now())
returns jsonb language sql stable security invoker set search_path = '' as $$
  with tz as (
    select coalesce((select zone.name from v3.profiles p join pg_timezone_names zone on zone.name = p.timezone
                      where p.id = p_user_id), 'UTC') as name
  ), clock as (
    select name, (p_now at time zone name)::date as today from tz
  ), log_days as (
    select (log.occurred_at at time zone clock.name)::date as day,
           case when log.kind = 'speaking_session' and jsonb_typeof(log.detail->'seconds') = 'number'
                then greatest((log.detail->>'seconds')::numeric, 0) else 0 end as seconds
      from v3.learner_activity_log log cross join clock
     where log.user_id = p_user_id and log.language_code = p_language_code
       and log.occurred_at between p_now - interval '366 days' and p_now
  ), active_days as (
    select day, row_number() over (order by day desc)::integer as position
      from (select distinct day from log_days cross join clock where day between today - 364 and today) days
  ), latest as (select max(day) as day from active_days)
  select jsonb_build_object(
    'cards', (select count(*) from v3.review_states
               where user_id = p_user_id and language_code = p_language_code and review_mode = 'concept_to_meaning'),
    'due_now', (select count(*) from v3.review_states
                 where user_id = p_user_id and language_code = p_language_code and review_mode = 'concept_to_meaning'
                   and due_at <= p_now),
    'lapses', (select coalesce(sum(lapses), 0) from v3.review_states
                where user_id = p_user_id and language_code = p_language_code and review_mode = 'concept_to_meaning'),
    'streak_days', (select count(*) from active_days d cross join latest cross join clock
                     where latest.day >= today - 1 and d.day = latest.day - (d.position - 1)),
    'minutes_last_7_days', (select trunc(coalesce(sum(seconds), 0) / 60) from log_days cross join clock
                            where day between today - 6 and today)
  );
$$;

revoke all on function v3.learner_profile_metrics(uuid, text, timestamptz) from public, anon, authenticated;
grant execute on function v3.learner_profile_metrics(uuid, text, timestamptz) to service_role;
