-- Restore the two checks defined by 023_review_states on installations that drifted.
-- Adding and validating in the same transaction leaves the data and original checks intact if validation fails.
alter table v3.review_states
  drop constraint if exists review_states_nonnegative_chk,
  add constraint review_states_nonnegative_chk check (
    stability >= 0 and difficulty between 0 and 10 and elapsed_days >= 0
    and scheduled_days >= 0 and reps >= 0 and lapses >= 0
  ),
  drop constraint if exists review_states_new_state_chk,
  add constraint review_states_new_state_chk check (
    fsrs_state <> 'new' or (reps = 0 and lapses = 0 and elapsed_days = 0
      and scheduled_days = 0 and last_reviewed_at is null)
  );
