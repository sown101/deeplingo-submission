-- DeepLingo v3 migration 002: constrained domain enums.

create type v3.concept_type as enum (
  'vocabulary',
  'grammar',
  'expression',
  'phrasal_verb',
  'idiom',
  'collocation',
  'pronunciation',
  'pragmatics',
  'cultural_note'
);

create type v3.learning_session_type as enum (
  'discovery',
  'practice',
  'review',
  'production'
);

create type v3.learning_session_status as enum (
  'planned',
  'active',
  'completed',
  'abandoned'
);

create type v3.activity_type as enum (
  'watch',
  'notice',
  'mcq',
  'cloze',
  'dictation',
  'recall',
  'translation',
  'sentence_build',
  'speaking',
  'shadowing',
  'roleplay',
  'review'
);

create type v3.attempt_status as enum (
  'started',
  'submitted',
  'cancelled'
);

create type v3.activity_status as enum (
  'planned',
  'active',
  'completed',
  'skipped'
);

create type v3.assessment_assessor_type as enum (
  'deterministic',
  'llm',
  'speech',
  'human'
);

create type v3.mastery_state as enum (
  'unknown',
  'introduced',
  'familiar',
  'understood',
  'weak',
  'mastered'
);

create type v3.review_mode as enum (
  'concept_to_meaning',
  'meaning_to_concept',
  'audio_to_text',
  'text_to_meaning',
  'production_prompt',
  'shadowing_prompt'
);

create type v3.fsrs_state as enum (
  'new',
  'learning',
  'review',
  'relearning'
);

create type v3.extraction_status as enum (
  'candidate',
  'verified',
  'rejected',
  'needs_review'
);

create type v3.content_source as enum (
  'youtube',
  'manual',
  'caption_track',
  'ai',
  'dictionary',
  'hybrid'
);

create type v3.skill_type as enum (
  'listening',
  'reading',
  'vocabulary',
  'grammar',
  'speaking',
  'pronunciation'
);

create type v3.processing_status as enum (
  'pending',
  'transcript_ready',
  'learning_objects_ready',
  'failed'
);
