-- SEC-03: learners can no longer create or delete their own profile row directly.
--
-- 029 let `authenticated` INSERT and DELETE its own v3.profiles row. Deleting it cascades to every
-- table keyed on the profile, including v3.learner_new_video_imports (O12), so delete-then-recreate
-- reset the AI import budget and also erased pedagogical state that only the server may write.
-- Profiles are created by learner initialization through the backend (service role), and neither
-- client writes Supabase tables directly. Learners keep own-row SELECT and UPDATE of their
-- non-pedagogical profile fields. Account deletion, when the product adds it, goes through the
-- backend. Forward-only.

revoke insert, delete on v3.profiles from anon, authenticated;

drop policy if exists "Users can insert own profile" on v3.profiles;
drop policy if exists "Users can delete own profile" on v3.profiles;
