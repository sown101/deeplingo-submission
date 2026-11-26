-- 6A-4: exact, half-open Unicode-codepoint occurrence spans.
-- Existing LearningObject/Concept IDs and learner-history FKs remain stable.

alter table v3.learning_objects
  add column if not exists start_codepoint integer,
  add column if not exists end_codepoint integer;

alter table v3.learning_objects
  add constraint learning_objects_codepoint_span_chk check (
    (start_codepoint is null and end_codepoint is null)
    or (start_codepoint >= 0 and end_codepoint > start_codepoint)
  );

-- Only a unique exact substring is safe to backfill. If two historical rows
-- for one Concept claim that same substring, keep both unresolved instead of
-- inventing which LearningObject owns the occurrence.
with matches as (
  select lo.id, lo.concept_id, lo.transcript_segment_id, lo.evidence_text,
         ts.text as source_text,
         strpos(ts.text, lo.evidence_text) as first_position,
         char_length(lo.evidence_text) as evidence_length
  from v3.learning_objects lo
  join v3.transcript_segments ts on ts.id = lo.transcript_segment_id
  where lo.start_codepoint is null and lo.end_codepoint is null
), unique_matches as (
  select id, concept_id, transcript_segment_id,
         first_position - 1 as resolved_start,
         first_position - 1 + evidence_length as resolved_end
  from matches
  where first_position > 0
    and strpos(substring(source_text from first_position + 1), evidence_text) = 0
), nonconflicting as (
  select *, count(*) over (
    partition by concept_id, transcript_segment_id, resolved_start, resolved_end
  ) as same_concept_rows
  from unique_matches
)
update v3.learning_objects lo
set start_codepoint = safe.resolved_start,
    end_codepoint = safe.resolved_end
from nonconflicting safe
where lo.id = safe.id and safe.same_concept_rows = 1;

create unique index if not exists learning_objects_concept_segment_span_uidx
  on v3.learning_objects
    (concept_id, transcript_segment_id, start_codepoint, end_codepoint)
  where start_codepoint is not null;

create or replace function v3.validate_learning_object_occurrence_span()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  source_text text;
  source_video_id uuid;
begin
  if tg_op = 'UPDATE' then
    if old.start_codepoint is not null and (
      new.start_codepoint is distinct from old.start_codepoint
      or new.end_codepoint is distinct from old.end_codepoint
      or new.evidence_text is distinct from old.evidence_text
      or new.transcript_segment_id is distinct from old.transcript_segment_id
      or new.concept_id is distinct from old.concept_id
    ) then
      raise exception 'A grounded LearningObject occurrence cannot move';
    end if;
  end if;

  if new.start_codepoint is null or new.end_codepoint is null then
    if tg_op = 'INSERT' or not (new.start_codepoint is null and new.end_codepoint is null) then
      raise exception 'New LearningObjects require paired occurrence spans';
    end if;
    -- Historical unresolved rows may still receive non-identity enrichment.
    return new;
  end if;

  select s.text, t.video_id into source_text, source_video_id
  from v3.transcript_segments s
  join v3.video_transcripts t on t.id = s.transcript_id
  where s.id = new.transcript_segment_id;
  if source_text is null or source_video_id is distinct from new.video_id
     or new.start_codepoint < 0
     or new.end_codepoint <= new.start_codepoint
     or new.end_codepoint > char_length(source_text)
     or substring(source_text from new.start_codepoint + 1
                  for new.end_codepoint - new.start_codepoint) <> new.evidence_text then
    raise exception 'LearningObject occurrence is not grounded in its source segment';
  end if;
  return new;
end;
$$;

revoke all on function v3.validate_learning_object_occurrence_span() from public;
drop trigger if exists validate_learning_object_occurrence_span on v3.learning_objects;
create trigger validate_learning_object_occurrence_span
  before insert or update on v3.learning_objects
  for each row execute function v3.validate_learning_object_occurrence_span();

create or replace function v3.preserve_grounded_transcript_segment_text()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.text is distinct from old.text and exists (
    select 1 from v3.learning_objects lo
    where lo.transcript_segment_id = old.id
  ) then
    raise exception 'Transcript text with LearningObjects is immutable';
  end if;
  return new;
end;
$$;

revoke all on function v3.preserve_grounded_transcript_segment_text() from public;
drop trigger if exists preserve_grounded_transcript_segment_text on v3.transcript_segments;
create trigger preserve_grounded_transcript_segment_text
  before update of text on v3.transcript_segments
  for each row execute function v3.preserve_grounded_transcript_segment_text();

comment on column v3.learning_objects.start_codepoint is
  'Zero-based Unicode code point offset into the exact TranscriptSegment.text; inclusive.';
comment on column v3.learning_objects.end_codepoint is
  'Zero-based Unicode code point offset into the exact TranscriptSegment.text; exclusive.';
