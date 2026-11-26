-- One learning log (owner 2026-11-18): v3.learner_practice_events and v3.learner_speaking_activity go.
--
-- Since 2026-11-14 every flow that wrote them also wrote v3.learner_activity_log, and the backend now writes the
-- learning log only. Apply this after that backend is deployed: the previous backend still writes both tables.
--   * Dictation checks, lookups and region-question answers are copied with the client_event_id the backend uses
--     (`dictation:<id>`, `lookup:<id>`, `region_question:<id>`), so the rows already written twice stay once.
--   * Conversation rows of the speaking table older than the first learning-log row become `speaking_session`
--     rows; later ones are already in the log, as are all shadowing rows.
--   * `region_opened`, `companion_turn` and `session_summarized` events fed only the removed session summary and
--     are not kept.
-- v3.speaking_sessions (the state of a speaking analysis) and v3.target_events (word-use evidence for the usage
-- ladder) are not activity rows and stay.

-- Order matters: the conversation rows are copied FIRST. Their cutoff is the oldest row the learning log held
-- before this migration; copying the practice rows first moved that cutoff back and left the older
-- conversations out. (Development ran the first version of this file, which had the order reversed: its 6
-- conversations of 8-15 November, test data, were not copied before the tables were dropped.)

insert into v3.learner_activity_log (user_id, language_code, client_event_id, kind, outcome, detail, occurred_at)
select a.user_id, a.language_code, 'speaking_activity:' || a.id::text, 'speaking_session', 'done',
       jsonb_build_object('seconds', a.seconds, 'turns', a.turns, 'reuse_words', to_jsonb(a.reuse_words)),
       a.occurred_at
  from v3.learner_speaking_activity a
 where a.source = 'conversation'
   and a.occurred_at < coalesce((select min(l.occurred_at) from v3.learner_activity_log l), 'infinity'::timestamptz)
on conflict (user_id, client_event_id) do nothing;

insert into v3.learner_activity_log (user_id, language_code, client_event_id, kind, item_type, item_id,
                                     source_type, source_id, outcome, score, detail, occurred_at)
select e.user_id, v.original_language_code,
       case e.kind when 'dictation_checked' then 'dictation:' when 'word_lookup' then 'lookup:'
                   else 'region_question:' end || e.id::text,
       case e.kind when 'dictation_checked' then 'dictation' when 'word_lookup' then 'lookup'
                   else 'region_question' end,
       'segment', e.segment_id::text, 'video_region', e.library_item_id::text,
       case
         when e.kind = 'word_lookup' then 'done'
         when e.kind = 'region_question_answered' then
           case when (e.payload->>'correct')::boolean then 'correct' else 'incorrect' end
         when coalesce((e.payload->>'total')::int, 0) > 0
              and (e.payload->>'correct')::int = (e.payload->>'total')::int then 'correct'
         when coalesce((e.payload->>'correct')::int, 0) > 0 then 'partial'
         else 'incorrect'
       end,
       case when e.kind = 'dictation_checked' and coalesce((e.payload->>'total')::int, 0) > 0
            then round(100.0 * (e.payload->>'correct')::int / (e.payload->>'total')::int, 1) end,
       case e.kind
         when 'dictation_checked' then jsonb_build_object('total', e.payload->'total', 'correct', e.payload->'correct',
                                                          'missed', coalesce(e.payload->'missed', '[]'::jsonb),
                                                          'level', e.payload->'level')
         when 'word_lookup' then jsonb_build_object('text', e.payload->'text')
         else jsonb_build_object('question_id', e.payload->'question_id')
       end,
       e.created_at
  from v3.learner_practice_events e
  join v3.learner_videos lv on lv.id = e.library_item_id and lv.user_id = e.user_id
  join v3.videos v on v.id = lv.video_id
 where e.kind in ('dictation_checked', 'word_lookup', 'region_question_answered')
   and e.segment_id is not null and v.original_language_code is not null
on conflict (user_id, client_event_id) do nothing;

drop table v3.learner_practice_events;
drop table v3.learner_speaking_activity;
