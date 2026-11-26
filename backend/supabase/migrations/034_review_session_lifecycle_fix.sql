-- DeepLingo v3 migration 034: review session lifecycle corrective fix.
--
-- 5H review sessions intentionally contain multiple review materializations.
-- Migration 032's one-materialization-per-session constraint is obsolete, but
-- opportunity-level uniqueness remains the idempotency authority.

alter table v3.review_materializations
  drop constraint if exists review_materializations_session_unique;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'review_materializations_opportunity_unique'
      and conrelid = 'v3.review_materializations'::regclass
  ) then
    raise exception 'review_materializations_opportunity_unique constraint is required';
  end if;
end;
$$;

comment on table v3.review_materializations is
  'Durable idempotency reservation for one materialized review opportunity from a specific ReviewState version. Multiple materializations may now belong to one 5H review LearningSession.';
