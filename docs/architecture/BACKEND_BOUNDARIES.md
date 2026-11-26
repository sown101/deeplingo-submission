# Backend bounded modules and dependency rules

Package structure and dependency rules for `backend/app`. All rules below are machine-checked by
`backend/.importlinter` through `tests/architecture/test_import_boundaries.py`; a broken
contract is a failing test. Paths are relative to `backend/app`.

## Package map

| Package | Holds |
|---|---|
| `main.py` | ASGI entry (`app = create_app()`) |
| `bootstrap/api.py`, `bootstrap/worker.py` | HTTP app factory; Celery `-A` entrypoint (task imports, beat, process hooks) |
| `bootstrap/wiring/<module>.py` | the only place concrete repositories/adapters/services are constructed |
| `platform/` | config, logging, Supabase clients, Celery app, persistence base, rate limiting, LLM port + OpenAI-compatible transport |
| `kernel/` | `ActivityType` (shared vocabulary) and `region_ids` (the id of a study region: its first and last sentence) |
| `modules/identity` | principal, token verifier port, JWT verifier, auth dependencies, `/me` |
| `modules/content` | catalog, Concepts/occurrences, ingestion, extraction/resolution/enrichment/preparation, Library, playback, transcript sources (YouTube captions or Gemini YouTube-URL transcription + YouTube Data API), dictionary provider, Celery tasks (`worker/`) |
| `modules/activity` | learning log (append-only, idempotent by client_event_id) and study requests; every flow records through `activity.contracts` |
| `modules/learner` | profiles/preferences, targets (saved concepts, daily gate, usage ladder), word lists and bulk import, video coverage, companion memory |
| `modules/learning` | the Notebook's skipped-word list, speaking practice, and the agent (`application/agent/`, restructure phase 4): one core (`AgentSession`, `ContextBuilder`, `ToolRegistry`, `Scaffolding`, prompts, evals) with a voice channel (Gemini Live) and a text channel (turn-based, also typed) |
| `modules/review` | review states/events, the one FSRS grade mapping (`domain/grades.py`), FSRS scheduling, the due forecast |
| `modules/progress` | progress numbers (restructure phase 5): one read of the learner's own log rows and review states, summed into streak, heatmap, cards by FSRS state, accuracy per kind, pronunciation per day, grammar, regions and speaking minutes |
| `modules/practice` | the exercise engine (restructure phase 2): one generator and one grader per exercise type, review decks per language, grammar lessons/exercises/progress, and the notebook memory-rating |

Each module: `contracts.py` (public surface), `domain/`, `application/` (use cases,
`ports.py`), `infrastructure/`, `api/`, optional `worker/`. Tests live in
`backend/tests/<module>/`, operational scripts in `backend/scripts/<module>/`.

## Rules

1. **Privacy.** Another module is imported only through its `contracts.py`. Exception
   by design: other modules' API layers may import `modules/identity/api/dependencies.py`
   (FastAPI authentication dependencies).
2. **Thin contracts.** `contracts.py` re-exports published domain values, enums, errors
   and pure functions; never repositories, adapters or concrete services.
3. **Ports.** Cross-module behavior/data goes through consumer-owned
   `application/ports.py` Protocols listing only the methods used, wired in
   `bootstrap/wiring/<module>.py`. Never pass a concrete repository across modules by type.
4. **Layers.** `api | worker | infrastructure` -> `application` -> `domain`. Entry
   points reach infrastructure only through `bootstrap.wiring`.
5. **Domain purity.** Standard library, pydantic, own module and other modules'
   contracts only; no FastAPI, Supabase, httpx/requests, OpenAI, Celery, Redis, fsrs,
   JWT, Google or YouTube SDKs, `app.platform` or `app.bootstrap`.
6. **Application purity.** No frameworks, vendor SDKs, settings, Supabase client or
   composition; collaborators and configuration values arrive through constructors.
7. **Value DAG.** `domain` and `contracts` import only modules below them:
   `identity`/`kernel` -> `activity` -> `content` -> `learner` -> `learning` ->
   `review` -> `practice`. Back-edges are `TYPE_CHECKING` annotations or ports.
8. **Persistence.** Each repository lives in the module that owns its table. SQL RPCs
   are the authoritative boundary for atomicity, uniqueness, CAS, idempotency,
   fencing and multi-table commits. Grading, Evidence and FSRS math never move into SQL.
9. **No shims.** Moves are hard cuts with every importer, test and script rewritten.
10. **Server authority.** Learner clients submit learner-owned input only. They never
    control expected answers, canonical activity payloads, grading truth, Evidence,
    mastery, skills, review scheduling, FSRS state or provenance. A learner-mounted
    route exists only for a real product caller, must not accept server-authority
    fields, and proof/diagnostic plumbing is never learner-mounted.

## Module responsibilities

| Module | Owns | Key application services | Tables (own repositories) |
|---|---|---|---|
| identity | verified principal, authorization primitives | `TokenVerifier` port; FastAPI auth dependencies (`get_current_user`, `require_self_scoped_user`) | none (Supabase Auth) |
| content | reference catalog, Concept semantic identity, exact occurrences, Library, preparation, playback | `ContentIngestionService`, `CandidateResolutionService`, `LearningObjectEnrichmentService`, `LearningContentPreparationService`, `LearnerLibraryService`, `LibraryOccurrenceService` (trusted Library sentences), `VideoPlaybackService`, `SegmentTranslationService` (AI sentence translations shared by language pair), `VideoWorkspaceService`, `ConceptInteractionService`, `LanguageCatalogService` | languages, channels, videos, video_transcripts, transcript_segments, segment_translations, romanization_systems, segment_romanizations, dictionary_entries, concepts, concept_dictionary_links, learning_objects, learner_videos, learner_video_workspaces, saved_concepts, learner_new_video_imports, example_sentences, corpus_sentences, video_work_intents (+ playback/claim views) |
| learner | language profile/preferences, saved words and word groups, video words, consent, personalization signals, kept speech transcripts | `LearnerModelService`, `MyWordsService` | profiles, user_language_preferences, word_groups, word_group_items, word_group_import_rows, learner_video_words, target_events, learner_agent_consent, learner_personalization_signals, learner_speech_transcripts |
| learning | speaking practice, the agent | `ShadowingPracticeService`, agent `TextChannel` and `VoiceChannel` over one core | speaking_sessions, companion_plans |
| activity | learning log and study requests; bounded reads by language | `ActivityService` (`record` never raises) | learner_activity_log, learner_study_requests |
| review | scheduling (FSRS), the one grade mapping, the due forecast | `ReviewForecastService` | review_states (`language_code` = the deck), review_events |
| practice | exercise generation and grading for words (flashcard, choice, listening, cloze, pronunciation, writing), decks per language, grammar from the approved banks (no FSRS) | `ReviewService` (due, answer: grade + FSRS at most once per card per pass + one log row in `v3.submit_review_answer`), `GrammarService` (overview, exercises, answer, lesson; redo list from `grammar_redo` requests; legacy grammar-review shapes) | learner_grammar_progress |

Do not split Library, LLM or FSRS into standalone business modules.

## Cross-module interactions

| Consumer -> provider | How |
|---|---|
| Learning -> Content | reader ports for Concepts, LearningObjects, segments, transcripts, videos, translations, romanizations; content values from `content.contracts` |
| Learning -> Learner | preference and target reader ports via `learner.contracts` |
| Learning (agent) -> Activity/Review/Practice/Learner/Content | the `AgentFacts` port (`application/agent/ports.py`), implemented by `LearnerFacts` in `bootstrap/wiring/agent.py`: the learner's log rows and study requests (one learner, one language, capped), due counts per deck, approved grammar points and lessons, the profile brief; study requests are created through the activity service after the item is checked to exist in that language |
| Review -> Content/Learner | reader ports for content context and preferences |
| All API layers -> Identity | `identity.api.dependencies`; principal value via `identity.contracts` |
| Practice -> Review | review values and the grade mapping via `review.contracts`; the FSRS adapter is passed in by `bootstrap/wiring/practice.py` |
| Practice -> Content/Learner/Learning | word cards built from content repositories passed in by wiring; speech parsing via `learning.contracts`; the meaning-option helpers are practice's own; study requests through the activity service |
| Review answer / grammar answer -> many tables | `v3.submit_review_answer` (state + event + log row + closing word requests) and `v3.record_grammar_answer` (log row + progress + closing `grammar_redo`), owned by practice |

Ports wired in bootstrap keep imports acyclic. The `assessment` module and the learning-session engine were removed on 2026-11-15 (the Flutter app they served is gone). No internal event
bus exists; Celery tasks are processing commands, not inter-module events.

## API ownership

Base path `/api/v1/v3`. Selector IDs are always re-authorized against the verified
principal. The web client consumes learner-safe contracts; see
frontend architecture for the consumed subset.
S = server-authoritative values; L = learner-controlled inputs; F = forbidden client authority.

| Routes | Owner (router) | Auth | S | L | F |
|---|---|---|---|---|---|
| `GET /languages` | content (`api/languages.py`) | public | supported catalog | none | invented languages |
| `GET/PUT /learner/me/language-profile` (`user_id` query rejected, 422), `/learner/me/profile`, `POST /learner/me/initialize` | learner | JWT | own identity, supported choices | validated language choices | proficiency/mastery authority |
| `GET /learner/me/progress` | progress (`api/routes.py`) | JWT | the caller's own numbers, one language or all | `language`, `utc_offset_minutes` | any other learner's rows, results |
| `GET /learner/me/review-forecast` | review (`api/routes.py`) | JWT | due counts per day for the caller | `days`, `utc_offset_minutes` | review state/version/FSRS values |
| `POST/GET /learner/me/library/videos`, `GET .../{id}`, `POST .../{id}/retry`, `POST .../{id}/learning/retry` | content (`api/library.py`) | JWT | association owner, status, dedup, work intent | YouTube URL, owned item, explicit retry | global content/readiness/Concept targets |
| `GET .../{id}/playback`, `.../{id}/transcript`, `.../{id}/learning-objects/{lo}/concept` | content (`api/playback.py`) | JWT + association | source chain, exact occurrence, bound support language | selectors | invented spans/meanings/sense identity |
| `GET /learner/me/continue-learning` (M2.2) | content (`api/playback.py`) | JWT; workspace rows of the caller only, each rechecked as an owned, ready Library video | the latest of 5 recent workspaces with a saved position or region; the region only if it matches the current transcript; read-only | none | item choice, position, region, writes of any kind |
| `POST .../{id}/lookup` | content (`api/playback.py`) | JWT + association; segment must belong to the video; 120 lookups/hour per learner | server-derived text of the selected span, longest dictionary unit, `word_lookup_sense_v1` choice among offered `sense_id`s, read-only | segment selector + code-point span | free text, invented senses, writes of any kind |
| `GET/POST /me/words`, `DELETE /me/words/{concept_id}` | learner (`api/routes.py`), Concept resolution in content (`WordConceptService`) | JWT; lookup re-grounded in an owned segment, occurrence must be in an owned video, dictionary language must be learned | Concept (dictionary sense or the video's prepared Concept), saved/known list, mastery and next review (read) | source + selectors (span and offered `sense_id`, entry + sense, or occurrence) | `concept_id`, `list`/`known`, user IDs, mastery or review values |
| `GET /me/dictionary/search` | content (`api/playback.py`) | JWT; shares the lookup rate limit | dictionary entries and senses, read-only | language + query text | writes of any kind |
| `GET /learner/me/review/decks`, `GET /learner/me/review/{language}/due` | practice (`api/routes.py`) | JWT; saved, not known words of the caller in that language | due and new counts per language; the pass's cards with exercises built on the server, no answer keys | language, mode, optional chosen words | answer keys, schedule values |
| `POST /learner/me/review/answers`, `POST /learner/me/review/answers/pronunciation`, `GET /learner/me/review/cards/{concept_id}/audio` | practice (`api/routes.py`) | JWT; the word must be the caller's saved word in that language | grade, FSRS grade and transition (once per card per pass), one log row; a retried `client_event_id` returns the stored result; audio chosen by concept id | `client_event_id`, `pass_id`, the shown option / typed text / own rating / WAV, hint flag, response time | correctness, grade, score, schedule values |
| `GET /learner/me/grammar/{language}`, `GET .../exercises`, `POST /learner/me/grammar/answers`, `POST /learner/me/grammar/lessons` | practice (`api/routes.py`) | JWT; approved banks of the language and the profile's support language | lessons, exercises without keys, grading, progress per point, the redo list | exercise id, option id, `client_event_id` | correctness, explanations before answering |
| `POST /learner/me/words/{concept_id}/memory-rating` | practice (`api/routes.py`) | as above | the notebook flashcard rating, run through the engine as a flashcard answer | rating, optional event id | as above |
| `POST .../{id}/shadowing/assessments` | learning (`api/speaking.py`) | JWT + Library/segment chain | server-chosen reference, provider result, grounded LLM output | selectors + raw WAV | scores, Evidence, mastery, review effects, client-supplied topic/hint text |
| `GET .../{id}/regions/{region}/result` (phase 3) | learning (`api/region_result.py`) | JWT + the caller's own Library item; the learner's own log rows of that region | counts and means of dictation, shadowing, questions, lookups and saved words in one study region | the region id | anyone else's rows, scores computed by the client |
| `POST .../{id}/translations` (phase 3) | content (`api/playback.py`) | JWT + owned, ready Library video; shares the lookup rate budget | sentences translated once into the learner's support language and stored for every learner with that pair | nothing but the item id | the text to translate, the language |
| `GET .../{id}/region-questions`, `POST .../{id}/region-questions/{question_id}/answer` | learning (`api/region_questions.py`, M1 S6; questions read from content through a wiring adapter) | JWT + Library/video/current transcript/current region chain; client UUID for idempotency | questions without answer keys; server check of the chosen option, key, quote and explanation after answering | the chosen option index | scores, Evidence, mastery, review effects, answer keys before answering, client-reported correctness |
| `POST .../{id}/session-summary` | learning (`api/practice_log.py`, M1 S7) | JWT + Library/video/current region chain; client UUID for idempotency | counts of this session rebuilt from the server's practice log, next part | an event UUID | client counts, scores, completion, Evidence, mastery, review effects |
| `POST .../{id}/practice-events/{dictation,lookup}` | learning (`api/practice_log.py`, M1 S4) | JWT + Library/video/current-original-segment chain; client UUID for idempotency | server re-check of the Dictation answer against the transcript, server text of a lookup span | selectors, raw Dictation answer, client-reported hint flag | scores, Evidence, mastery, review effects, stored raw answers |
| `GET /learner/me/activity`, `GET /learner/me/study-requests`, `POST .../study-requests/{id}/dismiss` | activity (`api/routes.py`) | JWT; every query names the caller and one language | the caller's log rows (capped at 200) and study requests | filters, a dismiss | writing log rows, other learners' rows |
| `GET /learner/me/agent/memory`, `DELETE .../memory/{memory_id}`, `DELETE .../memory` (agent v2 phase 3) | learning (`api/agent_memory.py`) | JWT; every query names the caller | the caller's own remembered rows (newest first, at most 40): `{items: [{id, kind, text, language_code, created_at}]}`; 404 for a row that is not the caller's; no writes by the learner | the row id | other learners' rows, creating or editing memory |
| `POST /learner/me/plan/items/{item_id}/undo` (agent v2 phase 4) | learning (`api/study_plan.py`) | JWT; the item is read with the caller's id, so another learner's item is a 404 | reverses one change the agent made to today's tasks: body `{"change": "added" \| "removed"}` (added = the task is dismissed, removed = it is open again), returns the plan item; repeating it is harmless; a task the learner already started is a 409 `plan_item_decided` | the item id and which change | other learners' items, any other status change, composing a plan |
| `POST /learner/me/companion/{sessions,turns,finish}` (the agent's text channel; the web fallback) | learning (`api/speaking.py`) | JWT + Library ownership rechecked per turn, signed learner-bound companion ticket | server-built context (video or the learner's study region, due Concepts or recent items, the learner context block), recent practice of the region from the learning log, validated `companion-turn-v4` output (optional practice suggestion on an offered region line; a correction's grammar point becomes a `grammar_redo` request only when it is an approved key), read tools on the learner's own data, synthesised reply audio | entry point + selectors, signed ticket, raw WAV or a typed turn (at most 300 characters, never both), or, since agent v2 phase 4, a help button `request` (`hint`, `explain`, `natural`, `suggest`; with words, audio or alone; at most 20 per conversation) and the learner's local `day` (names the plan the agent may edit; the turn also returns `actions`: cards that open a review of the learner's own saved words or a video part, or report a change to today's tasks) | scores, Evidence, mastery, review effects, tool choice of whose data, provider keys |
| `WS /learner/me/companion/realtime` (the agent's voice channel) | learning (`api/realtime.py`) | first message carries the JWT; `AGENT_CHANNELS` lists `voice`, development/test only, listed learner IDs; consent and limits checked before the provider opens | the same context and ToolRegistry as the text channel; every function call validated before anything reaches the learner; hints raised by the server's scaffolding; transcript checked after each agent turn | selectors, 16 kHz PCM, control messages (help, explain, natural, suggest, end) | anything the model says unvalidated, other learners' data, audio storage |
| `GET/DELETE /learner/me/companion/memory[/{id}]`, `PUT .../memory/settings` | learner (`api/routes.py`) | JWT; every query filtered by CurrentUser.id | the learner's own notes and consent | consent boolean, note ID selector | other learners' notes, scores, mastery, review effects |
| `GET /`, `GET /health` | bootstrap | public | process facts | none | not a DB/broker/provider readiness check |

Retired and not mounted (404): `/learner/me/planner/*`, `/learner/me/relevance/*`,
`/learner/me/review-candidates/*`, `/learner/me/skills`, `/learner/me/review-queue`, `/learner/me/review-sessions*`, `POST .../{id}/learning-sessions` (B3, 2026-10-26), activity generate/validate/persist proof routes,
`POST /learner/me/session-activities/{id}/attempts` and `POST /learner/me/attempts/{id}/assess` (B4.2, 2026-10-26), numbered `/learner/me/attempts` create, and all non-V3 legacy routes.
Removed in restructure phase 2 (2026-11-14; no client called it): `POST /learner/me/words/{concept_id}/practice` (example practice).
Removed in the M1 lean pass (D3, 2026-10-20; no client, script, runbook or CI caller): `/me`,
`/profile`, `/language-preferences`, `GET /learner/me`, `GET /learner/me/preferences`,
`PUT /learner/me/preferences/{code}`, `/learner/me/concepts/{id}/mastery`, `/learner/me/review-states/{id}`,
and the content operator routes `/videos/ingest`, `/videos/{id}`, `/videos/{id}/transcripts`,
`/transcripts/{id}/segments`, `/extraction/candidates`, `/extraction/resolve`, `/learning-objects/{id}/enrich`.
`/learner/me/profile` stays.

For persistence and failure semantics see data authority; for
open items see the debt register.
