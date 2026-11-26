// Reviewed small examples of current FastAPI service emissions. Keep semantic
// cases here; values are stable placeholders, never learner/provider secrets.
export const ids = {
  libraryItem: "44444444-5555-6666-7777-888888888888",
  video: "55555555-6666-7777-8888-999999999999",
  segment: "33333333-4444-5555-6666-777777777777",
  learningObject: "22222222-3333-4444-5555-666666666666",
  session: "11111111-2222-3333-4444-555555555555",
  sessionActivity: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  attempt: "99999999-8888-7777-6666-555555555555",
} as const;

export const languages = [
  { code: "en", name_en: "English", name_native: "English", script: "Latn", is_active: true, display_order: 1 },
  { code: "vi", name_en: "Vietnamese", name_native: "Tiếng Việt", script: "Latn", is_active: true, display_order: 2 },
];

export const languageProfile = {
  learning_language: "en",
  support_language: "vi",
  is_complete: true,
};

export const uninitializedLanguageProfile = {
  learning_language: null,
  support_language: null,
  is_complete: false,
};

export const learnerInitialization = {
  user_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  profile_status: "reused",
};

export const librarySummary = {
  library_item_id: ids.libraryItem,
  video_id: ids.video,
  title: "A short English lesson",
  thumbnail_url: null,
  duration_ms: 19000,
  source: "youtube",
  processing_status: "ready",
  learning_status: "ready",
  learning_object_count: 3,
  learning_prepared_language_code: "vi",
  language_code: "en",
  added_at: "2026-09-29T10:00:00Z",
  failure: null,
};

export const libraryDetails = {
  pending: { ...librarySummary, processing_status: "pending", learning_status: "not_started" },
  processing: { ...librarySummary, processing_status: "processing", learning_status: "processing" },
  ready: librarySummary,
  noContent: { ...librarySummary, learning_status: "no_content", learning_object_count: 0, learning_prepared_language_code: null },
  learningFailed: { ...librarySummary, learning_status: "failed", failure: null },
  processingFailed: {
    ...librarySummary,
    processing_status: "failed",
    learning_status: "failed",
    failure: { code: "transcript_unavailable", retryable: false, message: "A usable transcript is not available for this video." },
  },
};

export const libraryDetail = {
  ...librarySummary,
  description: null,
  transcript_available: true,
};

export const libraryImport = { command_status: "accepted", item: libraryDetail };

export const playback = {
  library_item_id: ids.libraryItem,
  video_id: ids.video,
  provider: "youtube",
  external_video_id: "jNQXAC9IVRw",
  title: "A short English lesson",
  language_code: "en",
  duration_ms: 19000,
};

// M1 S1/S2 VideoWorkspaceView (GET .../workspace and both PUT saves).
export const workspace = {
  library_item_id: ids.libraryItem,
  position_ms: 520000,
  region: {
    transcript_id: ids.video,
    start_segment_id: ids.segment,
    end_segment_id: ids.segment,
    start_ms: 0,
    end_ms: 4000,
    segment_count: 1,
    // M1 S2 RegionPreparationView (S6: questions_status), as the backend serializes it.
    preparation: { status: "processing", usable_count: 0, retryable: false, reset_at: null, questions_status: null },
  },
  updated_at: "2026-10-19T08:40:00Z",
};

export const transcriptSegment = {
  segment_id: ids.segment,
  sequence: 1,
  text: "Hello world.",
  start_ms: 0,
  end_ms: 2500,
  translation: { language_code: "vi", text: "Xin chào thế giới." },
  romanizations: [],
  learning_objects: [{ learning_object_id: ids.learningObject, start_codepoint: 0, end_codepoint: 5 }],
};

export const transcript = {
  library_item_id: ids.libraryItem,
  language_code: "en",
  translation_language_code: "vi",
  segments: [transcriptSegment],
};

export const conceptInteraction = {
  library_item_id: ids.libraryItem,
  learning_object_id: ids.learningObject,
  expression: "Hello",
  occurrence_text: "Hello",
  source_segment_text: "Hello world.",
  start_codepoint: 0,
  end_codepoint: 5,
  learning_language_code: "en",
  support_language_code: "vi",
  contextual_meaning: "lời chào",
  explanation: null,
  meaning_provenance: "unverified",
  dictionary_sense: null,
};

// Mirrors backend ConceptInteractionView for a meaning translated from a dictionary sense.
export const conceptInteractionFromDictionary = {
  ...conceptInteraction,
  meaning_provenance: "dictionary",
  dictionary_sense: {
    headword: "hello",
    reading: null,
    part_of_speech: "intj",
    definition: "A greeting (salutation) said when meeting someone.",
    source_name: "Wiktionary",
    source_url: "https://en.wiktionary.org/wiki/hello",
    license_name: "CC BY-SA 4.0",
    license_url: "https://creativecommons.org/licenses/by-sa/4.0/",
  },
};

export const apiErrorBodies = {
  unauthorized401: { detail: "Not authenticated" },
  validation400: { detail: "Bad request" },
  notFound404: { detail: { code: "library_item_not_found", message: "Library item not found." } },
  submissionConflict409: { detail: "submission_conflict" },
  validation422: { detail: "Malformed learner response" },
  attemptUnavailable503: { detail: "attempt_persistence_unavailable" },
  practiceUnavailable503: { detail: { code: "practice_temporarily_unavailable", message: "Practice is temporarily unavailable. Please retry." } },
  internal500: { detail: "private internal diagnostic — must not be rendered" },
};
