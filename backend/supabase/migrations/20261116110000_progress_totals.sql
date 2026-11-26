-- Progress totals summed in the database (PRD 8.10).
--
-- The progress screen used to page up to 20 000 log rows and 20 000 cards to the API and sum them in Python. This
-- function returns the same totals in one call: rows per local day, graded attempts per kind, grammar points,
-- completed video regions, speaking time per week, cards per language and state, pronunciation sums per day and weak
-- words. The window is the 365 local days ending today at the learner's UTC offset; log and score rows are read from
-- one day before it so every offset is covered. The arithmetic matches `totals_from_rows` in
-- backend/app/modules/progress/domain/models.py, which the tests use as the reference.

create or replace function v3.learner_progress_totals(p_user_id uuid, p_language_code text, p_now timestamptz,
                                                      p_utc_offset_minutes integer)
returns jsonb language sql stable security invoker set search_path = '' as $$
  with win as (
    select make_interval(mins => p_utc_offset_minutes) as off,
           ((p_now at time zone 'UTC') + make_interval(mins => p_utc_offset_minutes))::date as today,
           p_now - interval '366 days' as since
  ), fetched as (
    select l.language_code, l.kind, l.outcome, l.item_type, l.item_id, l.source_type, l.source_id,
           ((l.occurred_at at time zone 'UTC') + w.off)::date as day,
           case when l.detail->>'seconds' ~ '^\s*[-+]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][-+]?[0-9]+)?\s*$'
                then greatest(0, trunc((l.detail->>'seconds')::numeric))::bigint end as seconds
      from v3.learner_activity_log l cross join win w
     where l.user_id = p_user_id and l.occurred_at >= w.since
       and (p_language_code is null or l.language_code = p_language_code)
  ), inwin as (
    select f.* from fetched f cross join win w where f.day between w.today - 364 and w.today
  ), cards as (
    select r.language_code, r.fsrs_state::text as state, r.due_at
      from v3.review_states r
     where r.user_id = p_user_id and r.review_mode = 'concept_to_meaning'
       and (p_language_code is null or r.language_code = p_language_code)
  ), scores as (
    select ((s.occurred_at at time zone 'UTC') + w.off)::date as day,
           s.pronunciation, s.accuracy, s.fluency, s.completeness, s.prosody, s.weak_words
      from v3.learner_pronunciation_scores s cross join win w
     where s.user_id = p_user_id and s.occurred_at >= w.since
       and (p_language_code is null or s.language_code = p_language_code)
       and ((s.occurred_at at time zone 'UTC') + w.off)::date between w.today - 364 and w.today
  )
  select jsonb_build_object(
    'days', coalesce((select jsonb_agg(jsonb_build_object('day', day, 'count', n) order by day)
                        from (select day, count(*) as n from inwin group by day) d), '[]'::jsonb),
    'graded', coalesce((select jsonb_agg(jsonb_build_object('kind', kind, 'attempts', n, 'correct', c) order by kind)
                          from (select kind, count(*) as n, count(*) filter (where outcome = 'correct') as c
                                  from inwin where outcome in ('correct', 'incorrect', 'partial') group by kind) g),
                       '[]'::jsonb),
    'grammar_learned', (select count(distinct (language_code, item_id)) from inwin
                         where kind = 'grammar_lesson' and item_type = 'grammar_point' and coalesce(item_id, '') <> ''),
    'grammar_correct', (select count(distinct (language_code, item_id)) from inwin
                         where kind = 'grammar_exercise' and outcome = 'correct' and item_type = 'grammar_point'
                           and coalesce(item_id, '') <> ''),
    'regions', (select count(distinct (language_code, source_id)) from inwin
                 where source_type = 'video_region' and coalesce(source_id, '') <> ''
                   and kind in ('dictation', 'shadowing', 'region_question')),
    'speaking_sessions', (select count(*) from inwin where kind = 'speaking_session'),
    'speaking_seconds', (select coalesce(sum(seconds), 0) from inwin where kind = 'speaking_session'),
    'weeks', coalesce((select jsonb_agg(jsonb_build_object('week', week, 'seconds', s) order by week)
                         from (select day - (extract(isodow from day)::int - 1) as week, coalesce(sum(seconds), 0) as s
                                 from inwin where kind = 'speaking_session' group by 1) k), '[]'::jsonb),
    'cards', coalesce((select jsonb_agg(jsonb_build_object('language_code', language_code, 'state', state,
                                                            'total', n, 'due', due) order by language_code, state)
                         from (select language_code, state, count(*) as n,
                                      count(*) filter (where due_at is not null and due_at <= p_now) as due
                                 from cards group by language_code, state) c), '[]'::jsonb),
    'scores', coalesce((select jsonb_agg(jsonb_build_object(
                           'day', day, 'sessions', n,
                           'pronunciation_sum', sum_p, 'pronunciation_count', n_p, 'accuracy_sum', sum_a,
                           'accuracy_count', n_a, 'fluency_sum', sum_f, 'fluency_count', n_f,
                           'completeness_sum', sum_c, 'completeness_count', n_c, 'prosody_sum', sum_r,
                           'prosody_count', n_r) order by day)
                         from (select day, count(*) as n,
                                      sum(pronunciation) as sum_p, count(pronunciation) as n_p,
                                      sum(accuracy) as sum_a, count(accuracy) as n_a,
                                      sum(fluency) as sum_f, count(fluency) as n_f,
                                      sum(completeness) as sum_c, count(completeness) as n_c,
                                      sum(prosody) as sum_r, count(prosody) as n_r
                                 from scores group by day) p), '[]'::jsonb),
    'weak', coalesce((select jsonb_agg(jsonb_build_object('word', word, 'count', n))
                        from (select word, count(*) as n
                                from scores, jsonb_array_elements_text(case when jsonb_typeof(scores.weak_words) = 'array'
                                    then scores.weak_words else '[]'::jsonb end) as word
                               group by word) w), '[]'::jsonb),
    'languages', coalesce((select jsonb_agg(code order by code)
                             from (select language_code as code from fetched
                                   union select language_code from cards) l), '[]'::jsonb)
  );
$$;

revoke all on function v3.learner_progress_totals(uuid, text, timestamptz, integer) from public, anon, authenticated;
grant execute on function v3.learner_progress_totals(uuid, text, timestamptz, integer) to service_role;
