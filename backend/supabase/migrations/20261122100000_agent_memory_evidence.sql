-- DRAFT. Not applied to any environment. Applying it needs the owner's approval for that environment. Forward-only.
--
-- Agent harness plan, phase 5: the agent's notes about a learner keep the turns they came from. After a voice
-- conversation whose turns were kept (FR-3.11, both consents), a background step proposes notes from the learner's
-- own words; the server keeps a note only when its quote is in one of those turns, and stores that turn as evidence.
--   * evidence: up to three {"session_id", "turn_index"} references to v3.learner_speech_transcripts rows of the same
--     learner. A reference whose turn was deleted (by the learner or the 12-month expiry) simply finds nothing.
--   * source: 'agent' (the agent's remember tool, during a conversation) or 'consolidated' (the background step).
-- Existing rows get evidence [] and source 'agent'. The learner still sees, exports and deletes every row.
-- Backend-only, as before: no grant to anon or authenticated.

alter table v3.learner_agent_memory
  add column if not exists evidence jsonb not null default '[]'::jsonb,
  add column if not exists source text not null default 'agent';

alter table v3.learner_agent_memory
  drop constraint if exists learner_agent_memory_source_check,
  add constraint learner_agent_memory_source_check check (source in ('agent', 'consolidated')),
  drop constraint if exists learner_agent_memory_evidence_check,
  add constraint learner_agent_memory_evidence_check
    check (jsonb_typeof(evidence) = 'array' and jsonb_array_length(evidence) <= 3);

-- The insert-and-trim of add_agent_memory, with the evidence and the source.
create or replace function v3.add_agent_memory_with_evidence(p_user_id uuid, p_kind text, p_text text,
                                                             p_language_code text, p_max_rows integer,
                                                             p_evidence jsonb, p_source text)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_id uuid;
begin
  perform pg_advisory_xact_lock(hashtextextended('learner_agent_memory:' || p_user_id::text, 0));
  insert into v3.learner_agent_memory (user_id, kind, text, language_code, created_at, evidence, source)
  values (p_user_id, p_kind, p_text, p_language_code, clock_timestamp(), coalesce(p_evidence, '[]'::jsonb), p_source)
  returning id into v_id;
  delete from v3.learner_agent_memory m
   where m.user_id = p_user_id
     and m.id in (select r.id from v3.learner_agent_memory r
                   where r.user_id = p_user_id
                   order by r.created_at desc, r.id desc
                   offset greatest(p_max_rows, 1));
  return v_id;
end;
$$;

revoke all on function v3.add_agent_memory_with_evidence(uuid, text, text, text, integer, jsonb, text)
  from public, anon, authenticated;
grant execute on function v3.add_agent_memory_with_evidence(uuid, text, text, text, integer, jsonb, text)
  to service_role;
