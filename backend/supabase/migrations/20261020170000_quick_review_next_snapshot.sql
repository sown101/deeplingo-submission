-- M1 lean pass: Quick review's next reads everything it needs in one round trip (owner approved
-- 2026-10-20). Read only: nothing is written, nothing is graded and no FSRS math runs here.
--
-- One consistent snapshot of the learner's own batch: the session (only when it is this learner's),
-- its questions in order, the questions whose answer was assessed and applied, the first open question
-- (not skipped or completed, no applied answer) and, when that question is grounded in a video
-- occurrence, its trusted chain (occurrence, Concept, transcript segment, transcript). The server
-- rechecks the whole chain, the batch policy and the question payload in Python before serving it,
-- exactly as when it read each row separately. A skip that commits after this read is still refused
-- by the Attempt RPC (A25, `activity_closed`).

create or replace function v3.quick_review_next_snapshot(p_user_id uuid, p_session_id uuid)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_session v3.learning_sessions;
  v_open v3.session_activities;
  v_object v3.learning_objects;
  v_segment v3.transcript_segments;
begin
  select * into v_session from v3.learning_sessions where id = p_session_id and user_id = p_user_id;
  if v_session.id is null then
    return jsonb_build_object('session', null);
  end if;

  select a.* into v_open from v3.session_activities a
  where a.session_id = v_session.id and a.status not in ('skipped', 'completed')
    and not exists (
      select 1 from v3.attempts t
      join v3.assessment_applications ap on ap.attempt_id = t.id and ap.user_id = p_user_id
      where t.activity_id = a.id and t.user_id = p_user_id
    )
  order by a.position
  limit 1;

  if v_open.learning_object_id is not null then
    select * into v_object from v3.learning_objects where id = v_open.learning_object_id;
    if v_object.id is not null then
      select * into v_segment from v3.transcript_segments where id = v_object.transcript_segment_id;
    end if;
  end if;

  return jsonb_build_object(
    'session', to_jsonb(v_session),
    'activities', coalesce(
      (select jsonb_agg(to_jsonb(a) order by a.position) from v3.session_activities a
       where a.session_id = v_session.id),
      '[]'::jsonb),
    'applied_activity_ids', coalesce(
      (select jsonb_agg(distinct t.activity_id) from v3.attempts t
       join v3.assessment_applications ap on ap.attempt_id = t.id and ap.user_id = p_user_id
       join v3.session_activities a on a.id = t.activity_id
       where a.session_id = v_session.id and t.user_id = p_user_id),
      '[]'::jsonb),
    'open_activity_id', v_open.id,
    'learning_object', case when v_object.id is null then null else to_jsonb(v_object) end,
    'concept', case when v_object.id is null then null else
      (select to_jsonb(c) from v3.concepts c where c.id = coalesce(v_open.concept_id, v_object.concept_id)) end,
    'transcript_segment', case when v_segment.id is null then null else to_jsonb(v_segment) end,
    'transcript', case when v_segment.id is null then null else
      (select to_jsonb(tr) from v3.video_transcripts tr where tr.id = v_segment.transcript_id) end
  );
end;
$$;

revoke all on function v3.quick_review_next_snapshot(uuid, uuid) from public, anon, authenticated;
grant execute on function v3.quick_review_next_snapshot(uuid, uuid) to service_role;
