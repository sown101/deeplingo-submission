# DeepLingo PostgreSQL v3

This document describes the v3 PostgreSQL schema implemented under the `v3` schema namespace.
Legacy `public` tables remain in the database for historical data but are not used by the
backend; the authoritative migration list is `backend/supabase/migrations/`.

## Goals

DeepLingo v3 models an adaptive learning loop:

`real content -> learning objects -> saved words (targets) -> practice -> review -> next session`

The schema keeps these concepts separate:

- `dictionary_entries`: linguistic reference information.
- `concepts`: canonical learnable entities.
- `learning_objects`: context-specific evidence where a concept occurs.
- `review_states`: when and how the learner should review a concept.

## Namespace

All v3 objects are created in schema `v3`.
This avoids naming collisions with existing legacy tables such as `public.videos`, `public.subtitles`, `public.word_groups`, and `public.user_language_preferences`.

## Tables

Reference and content tables:

- `v3.languages`
- `v3.romanization_systems`
- `v3.channels`
- `v3.videos`
- `v3.video_transcripts`
- `v3.transcript_segments`
- `v3.segment_translations`
- `v3.segment_romanizations`
- `v3.dictionary_entries`
- `v3.concepts`
- `v3.concept_dictionary_links`
- `v3.learning_objects`

User-owned tables:

- `v3.profiles`
- `v3.user_language_preferences`
- `v3.review_states`
- `v3.review_events`
- `v3.saved_concepts`
- `v3.word_groups`
- `v3.word_group_items`
- `v3.learner_agent_memory` (agent v2 phase 3, draft migration `20261116095000_agent_memory.sql`, not applied: short
  free-text rows the agent remembers about a learner, backend-only, no grant to `anon`/`authenticated`)

## Ownership

User-owned rows use `auth.uid()` through RLS policies.
The backend must not trust client-supplied `user_id` values.

Public/reference content is readable by `anon` and `authenticated` where appropriate.
Ingestion and curation writes should be done from trusted backend/service-role contexts.

## JSONB Policy

Allowed JSONB fields:

- `metadata` for external provider metadata.
- `provider_metadata`.
- immutable review scheduling snapshots.
- raw AI diagnostics.
- optional user preference details.

Not allowed as JSONB:

- relationships
- ownership
- language identity
- translation rows
- romanization rows
- FSRS current fields
- statuses
- timestamps
- concept identity

## Important Invariants

`v3.learning_objects.video_id` must match the video reached through:

`learning_objects.transcript_segment_id -> transcript_segments.transcript_id -> video_transcripts.video_id`

This invariant is documented on the column and should be enforced in the backend service layer unless a future schema revision adds a composite denormalized constraint.

`watch` activities represent exposure. They create no Evidence without an assessed answer.

## Security

RLS is enabled for all v3 tables.
Policies use `to anon`, `to authenticated`, and `(select auth.uid())` patterns.
Content tables expose public reads where useful.
User-owned tables are isolated by the authenticated user or by ownership through parent tables.

Review events are intended to be append-only. The schema does not define user insert/update policies for review states or review events; trusted backend services should write these using server-side credentials.

## Seed Data

The seed migration inserts only reference data:

- English
- Vietnamese
- Chinese
- Japanese
- Korean
- Thai
- Arabic
- Hindi
- Russian

Romanization systems include Pinyin, Hepburn, Revised Romanization of Korean, RTGS, Arabic chat transliteration, ISO 233, IAST, ITRANS, ISO 9, and BGN/PCGN.

No fake users, mastery or reviews are seeded.
