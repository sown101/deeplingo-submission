-- M1 S6: comprehension questions about a study region (practice only).
--
-- Up to three multiple-choice questions per prepared region, generated once by the region
-- preparation worker and shared by every learner who studies that region. Each question cites an
-- exact quote of one region sentence. The answer key never leaves the server before the learner
-- answers; answers are checked by the API and kept only as a practice-log fact: never an Attempt,
-- Evidence, mastery, skill or ReviewState. Forward-only.

alter table v3.video_region_preparations
  add column if not exists questions_status text check (questions_status in ('ready', 'none', 'failed'));

create table if not exists v3.region_questions (
  id uuid primary key default extensions.gen_random_uuid(),
  region_preparation_id uuid not null references v3.video_region_preparations(id) on delete cascade,
  position integer not null check (position between 1 and 3),
  question text not null check (btrim(question) <> '' and char_length(question) <= 300),
  options jsonb not null check (jsonb_typeof(options) = 'array' and jsonb_array_length(options) = 4),
  correct_index integer not null check (correct_index between 0 and 3),
  evidence_segment_id uuid not null references v3.transcript_segments(id) on delete cascade,
  evidence_quote text not null check (btrim(evidence_quote) <> '' and char_length(evidence_quote) <= 300),
  explanation text not null check (btrim(explanation) <> '' and char_length(explanation) <= 400),
  generation_version text not null check (btrim(generation_version) <> ''),
  created_at timestamptz not null default now(),
  constraint region_questions_position_unique unique (region_preparation_id, position)
);

comment on table v3.region_questions is
  'M1 S6: comprehension MCQ of one prepared study region (global content, answer key server-only).';

alter table v3.region_questions enable row level security;
revoke all privileges on v3.region_questions from public, anon, authenticated;
grant all privileges on v3.region_questions to service_role;

-- The worker writes a region's questions under its own region claim, all at once.
create or replace function v3.write_claimed_region_questions(
  p_intent_id uuid, p_claim_token uuid, p_claim_epoch bigint, p_status text, p_questions jsonb
) returns integer language plpgsql security invoker set search_path = '' as $$
declare i v3.video_work_intents%rowtype; q jsonb; n integer := 0; segment uuid;
begin
  i := v3.lock_current_content_claim(p_intent_id, p_claim_token, p_claim_epoch, 'region_preparation');
  if p_status is null or p_status not in ('ready', 'none', 'failed') or jsonb_typeof(p_questions) <> 'array'
     or jsonb_array_length(p_questions) > 3
     or (p_status = 'ready') <> (jsonb_array_length(p_questions) > 0) then
    raise exception 'Invalid region questions' using errcode = '23514';
  end if;
  delete from v3.region_questions where region_preparation_id = i.region_preparation_id;
  for q in select value from jsonb_array_elements(p_questions) loop
    n := n + 1;
    segment := (q->>'evidence_segment_id')::uuid;
    if not v3.preparation_claim_covers_segment(i.stage, i.region_preparation_id, segment)
       or coalesce(position(q->>'evidence_quote' in (select text from v3.transcript_segments where id = segment)), 0) = 0 then
      raise exception 'Question evidence outside claimed region' using errcode = '23514';
    end if;
    insert into v3.region_questions (region_preparation_id, position, question, options, correct_index,
      evidence_segment_id, evidence_quote, explanation, generation_version)
    values (i.region_preparation_id, n, q->>'question', q->'options', (q->>'correct_index')::integer,
      segment, q->>'evidence_quote', q->>'explanation', q->>'generation_version');
  end loop;
  update v3.video_region_preparations set questions_status = p_status, updated_at = clock_timestamp()
    where id = i.region_preparation_id;
  return n;
end $$;

revoke all on function v3.write_claimed_region_questions(uuid, uuid, bigint, text, jsonb)
  from public, anon, authenticated;
grant execute on function v3.write_claimed_region_questions(uuid, uuid, bigint, text, jsonb) to service_role;

-- The practice log gains the fact that a region question was answered (server-checked).
alter table v3.learner_practice_events drop constraint if exists learner_practice_events_kind_check;
alter table v3.learner_practice_events add constraint learner_practice_events_kind_check
  check (kind in ('dictation_checked', 'shadowing_attempted', 'word_lookup', 'region_question_answered'));
