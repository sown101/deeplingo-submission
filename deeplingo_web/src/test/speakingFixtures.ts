// Shared speaking-practice API fixtures for tests.

const SEGMENT = "11111111-2222-3333-4444-555555555555";

export const shadowingPayload = {
  library_item_id: "aaaaaaaa-2222-3333-4444-555555555555",
  segment_id: SEGMENT,
  language_code: "en",
  reference_text: "Before the leaves fall.",
  recognized_text: "Before the leaves fall.",
  band: "good",
  scores: { pronunciation: 82.3, accuracy: 75, fluency: 95, completeness: 79, prosody: null },
  words: [
    { word: "before", accuracy: 97, error_type: "none", start_ms: 80, end_ms: 510, phonemes: [{ phoneme: "b", accuracy: 81 }] },
    { word: "leaves", accuracy: 40, error_type: "mispronunciation", start_ms: 520, end_ms: 820, phonemes: [] },
  ],
  attempt_duration_ms: 2000,
  reference_duration_ms: 3000,
  spoken_duration_ms: 740,
};
