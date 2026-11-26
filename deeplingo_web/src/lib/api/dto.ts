// Learner-safe DTO contracts extracted from backend domain models.
// No authority fields (expected answers, mastery, review state, provider
// diagnostics) are modeled; unknown fields are ignored defensively.

export type ProcessingStatus = "pending" | "processing" | "ready" | "failed";
export type LearningPreparationStatus =
  | "not_started"
  | "processing"
  | "ready"
  | "no_content"
  | "failed";

export type FailureCode =
  | "invalid_video_url"
  | "video_unavailable"
  | "transcript_unavailable"
  | "unsupported_content"
  | "processing_failed";

export interface LibraryVideoFailure {
  code: FailureCode;
  retryable: boolean;
  message: string;
}

export interface LibraryVideoSummary {
  library_item_id: string;
  video_id: string;
  title: string;
  thumbnail_url: string | null;
  duration_ms: number | null;
  source: string;
  processing_status: ProcessingStatus;
  learning_status: LearningPreparationStatus;
  learning_object_count: number;
  learning_prepared_language_code: string | null;
  language_code: string;
  added_at: string;
  failure: LibraryVideoFailure | null;
}

export interface LibraryVideoDetail extends LibraryVideoSummary {
  description: string | null;
  transcript_available: boolean;
}

export interface LearnerVideoImportResponse {
  command_status: string;
  item: LibraryVideoDetail;
}

export interface PlayableVideo {
  library_item_id: string;
  video_id: string;
  provider: "youtube";
  external_video_id: string;
  title: string;
  language_code: string;
  duration_ms: number | null;
}

export interface SegmentTranslationView {
  language_code: string;
  text: string;
}

export interface SegmentRomanizationView {
  system: string;
  text: string;
}

export interface LearningObjectOccurrenceView {
  learning_object_id: string;
  start_codepoint: number;
  end_codepoint: number;
  grammar_key?: string;
}

export interface TranscriptSegmentView {
  segment_id: string;
  sequence: number;
  text: string;
  start_ms: number;
  end_ms: number;
  translation: SegmentTranslationView | null;
  romanizations: SegmentRomanizationView[];
  learning_objects: LearningObjectOccurrenceView[];
}

export interface VideoTranscriptView {
  library_item_id: string;
  language_code: string;
  translation_language_code: string | null;
  segments: TranscriptSegmentView[];
}

// "dictionary" only when the meaning was translated from a credited dictionary sense.
export type MeaningProvenance = "dictionary" | "unverified";

export interface DictionarySenseView {
  headword: string;
  reading: string | null;
  part_of_speech: string | null;
  definition: string;
  source_name: string;
  source_url: string;
  license_name: string;
  license_url: string;
}

export interface ConceptInteractionView {
  library_item_id: string;
  learning_object_id: string;
  expression: string;
  occurrence_text: string;
  source_segment_text: string;
  start_codepoint: number;
  end_codepoint: number;
  learning_language_code: string;
  support_language_code: string;
  contextual_meaning: string;
  explanation: string | null;
  meaning_provenance: MeaningProvenance;
  dictionary_sense: DictionarySenseView | null;
}

export interface Language {
  code: string;
  name_en: string;
  name_native: string;
  script: string;
  is_active: boolean;
  display_order: number;
}

export interface LearnerLanguageProfile {
  learning_language: string | null;
  support_language: string | null;
  is_complete: boolean;
  // L1a: the learner's own level (CEFR for English, HSK for Chinese) and the daily new-word limit.
  declared_level?: string | null;
  daily_new_limit?: number;
}

// POST /learner/me/library/videos/{id}/lookup — meaning of any selected span (read-only).
export type LookupProvenance = "translated_from_sense" | "ai_unverified" | "dictionary_only" | "unavailable";

export interface LookupSourceView {
  name: string;
  license_name: string;
  license_url: string;
  entry_url: string;
}

export interface WordLookupView {
  segment_id: string;
  selection_start: number;
  selection_end: number;
  unit_start: number;
  unit_end: number;
  unit_text: string;
  unit_kind: "word" | "phrase";
  selection_is_part: boolean;
  headword: string | null;
  reading: string | null;
  part_of_speech: string | null;
  dictionary_gloss: string | null;
  sense_id: string | null;
  meaning: string | null;
  note: string | null;
  // Written by the model for this sentence: the structure, what it means here and new examples.
  pattern: string[];
  pattern_explanation: string | null;
  examples: { text: string; translation: string }[];
  context_before: string | null;
  context_after: string | null;
  meaning_provenance: LookupProvenance;
  level: string | null;
  source: LookupSourceView | null;
}
