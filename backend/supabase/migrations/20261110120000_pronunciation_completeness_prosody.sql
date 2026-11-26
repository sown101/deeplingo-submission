-- Owner request 2026-11-10: show every Azure sentence score on Progress, so each practice also keeps its average
-- completeness and prosody. Prosody exists only where Azure scores it (English), so both columns may be empty;
-- rows written before this migration have neither. Same table rules: backend-only, cascade, 12-month expiry.
-- Forward-only. Applying it to any environment needs the owner's approval for that environment.

alter table v3.learner_pronunciation_scores
  add column if not exists completeness numeric(5,1) check (completeness between 0 and 100),
  add column if not exists prosody numeric(5,1) check (prosody between 0 and 100);
