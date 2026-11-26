-- SEC-01: stop learners reading grading truth through the Data API.
--
-- 029 granted `authenticated` SELECT on v3.session_activities and v3.assessments, and 5L-1 only
-- revoked writes. Own-row RLS limits the rows but not the columns, so a signed-in learner could
-- read `expected_response_payload` for the activity they are answering and the assessment's
-- `raw_ai_diagnostics` directly from PostgREST. Learners already get the safe execution and
-- feedback projections through FastAPI (service role); neither client reads these tables
-- directly. The own-row select policies stay in place and simply have no grant to act on.
-- Forward-only.

revoke select on
  v3.session_activities,
  v3.assessments
from anon, authenticated;
