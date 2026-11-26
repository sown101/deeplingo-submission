import { ApiError } from "../../lib/api/errors";
import type {
  ConceptInteractionView,
  DictionarySenseView,
  MeaningProvenance,
  LearningObjectOccurrenceView,
  LookupProvenance,
  LookupSourceView,
  PlayableVideo,
  TranscriptSegmentView,
  VideoTranscriptView,
  WordLookupView,
} from "../../lib/api/dto";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;

export function parsePlayableVideo(raw: unknown): PlayableVideo {
  const r = object(raw, "Invalid playback response");
  if (r.provider !== "youtube") {
    throw new ApiError("parse", null, { message: "Unsupported media" });
  }
  const id = str(r.external_video_id, "external_video_id");
  if (!YOUTUBE_ID.test(id)) {
    throw new ApiError("parse", null, { message: "Unsupported media" });
  }
  return {
    library_item_id: uuid(r.library_item_id),
    video_id: uuid(r.video_id),
    provider: "youtube",
    external_video_id: id,
    title: str(r.title, "title"),
    language_code: str(r.language_code, "language_code"),
    duration_ms: intOrNull(r.duration_ms, 0),
  };
}

export function parseVideoTranscriptView(raw: unknown): VideoTranscriptView {
  const r = object(raw, "Invalid transcript response");
  const rawSegments = r.segments;
  if (!Array.isArray(rawSegments) || rawSegments.length === 0) {
    throw new ApiError("parse", null, { message: "Transcript unavailable" });
  }
  const segments: TranscriptSegmentView[] = [];
  for (const item of rawSegments) {
    segments.push(parseSegment(item));
  }
  segments.sort((a, b) => (a.start_ms !== b.start_ms ? a.start_ms - b.start_ms : a.sequence - b.sequence));
  const ids = new Set(segments.map((s) => s.segment_id));
  if (ids.size !== segments.length) {
    throw new ApiError("parse", null, { message: "Duplicate segment identity" });
  }
  const translationLanguage = nullableString(r.translation_language_code, "translation_language_code");
  return {
    library_item_id: uuid(r.library_item_id),
    language_code: str(r.language_code, "language_code"),
    translation_language_code: translationLanguage,
    segments,
  };
}

export function parseSegment(raw: unknown): TranscriptSegmentView {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new ApiError("parse", null, { message: "Invalid transcript segment" });
  }
  const r = raw as Record<string, unknown>;
  const start = r.start_ms;
  const end = r.end_ms;
  const sequence = r.sequence;
  const text = r.text;
  if (
    typeof start !== "number" || !Number.isSafeInteger(start) || start < 0 ||
    typeof end !== "number" || !Number.isSafeInteger(end) || end <= start ||
    typeof sequence !== "number" || !Number.isSafeInteger(sequence) || sequence < 1 ||
    typeof text !== "string" || text.trim().length === 0
  ) {
    throw new ApiError("parse", null, { message: "Invalid transcript segment" });
  }
  const codepointCount = [...text].length;
  const occurrences: LearningObjectOccurrenceView[] = [];
  if (!Array.isArray(r.learning_objects) || !Array.isArray(r.romanizations)) {
    throw new ApiError("parse", null, { message: "Invalid transcript annotations" });
  }
  for (const rawOccurrence of r.learning_objects) {
    occurrences.push(parseOccurrence(rawOccurrence, codepointCount));
  }
  occurrences.sort(compareOccurrences);
  return {
    segment_id: uuid(r.segment_id),
    sequence,
    text,
    start_ms: start,
    end_ms: end,
    translation: parseTranslation(r.translation),
    romanizations: r.romanizations.map(parseRomanization),
    learning_objects: occurrences,
  };
}

function parseOccurrence(raw: unknown, codepointCount: number): LearningObjectOccurrenceView {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new ApiError("parse", null, { message: "Invalid transcript occurrence" });
  }
  const r = raw as Record<string, unknown>;
  const start = r.start_codepoint;
  const end = r.end_codepoint;
  const id = r.learning_object_id;
  if (
    typeof start !== "number" || !Number.isSafeInteger(start) || start < 0 ||
    typeof end !== "number" || !Number.isSafeInteger(end) || end <= start ||
    typeof id !== "string" || !UUID_RE.test(id)
  ) {
    throw new ApiError("parse", null, { message: "Invalid transcript occurrence" });
  }
  if (end > codepointCount) throw new ApiError("parse", null, { message: "Invalid transcript occurrence" });
  const grammarKey = r.grammar_key;
  if (grammarKey !== undefined && (typeof grammarKey !== "string" || !/^[a-z]{2,3}\.[a-z0-9_.]+$/.test(grammarKey))) {
    throw new ApiError("parse", null, { message: "Invalid grammar annotation" });
  }
  return { learning_object_id: id, start_codepoint: start, end_codepoint: end,
    ...(grammarKey ? { grammar_key: grammarKey } : {}) };
}

function compareOccurrences(a: LearningObjectOccurrenceView, b: LearningObjectOccurrenceView): number {
  if (a.start_codepoint !== b.start_codepoint) return a.start_codepoint - b.start_codepoint;
  if (a.end_codepoint !== b.end_codepoint) return a.end_codepoint - b.end_codepoint;
  return a.learning_object_id < b.learning_object_id ? -1 : 1;
}

function parseTranslation(value: unknown): TranscriptSegmentView["translation"] {
  if (value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError("parse", null, { message: "Invalid transcript translation" });
  }
  const r = value as Record<string, unknown>;
  if (typeof r.language_code !== "string" || typeof r.text !== "string" || !r.text.trim()) {
    throw new ApiError("parse", null, { message: "Invalid transcript translation" });
  }
  return { language_code: r.language_code, text: r.text };
}

function parseRomanization(value: unknown): TranscriptSegmentView["romanizations"][number] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError("parse", null, { message: "Invalid transcript romanization" });
  }
  const r = value as Record<string, unknown>;
  if (typeof r.system !== "string" || !r.system.trim() || typeof r.text !== "string" || !r.text.trim()) {
    throw new ApiError("parse", null, { message: "Invalid transcript romanization" });
  }
  return { system: r.system, text: r.text };
}

export function parseConceptInteractionView(raw: unknown): ConceptInteractionView {
  const r = object(raw, "Invalid concept response");
  const source = str(r.source_segment_text, "source_segment_text");
  const occurrence = str(r.occurrence_text, "occurrence_text");
  const start = r.start_codepoint;
  const end = r.end_codepoint;
  if (
    typeof start !== "number" || !Number.isSafeInteger(start) || start < 0 ||
    typeof end !== "number" || !Number.isSafeInteger(end) ||
    end <= start || end > [...source].length
  ) {
    throw new ApiError("parse", null, { message: "Invalid concept occurrence" });
  }
  const sliced = [...source].slice(start, end).join("");
  if (sliced !== occurrence) {
    throw new ApiError("parse", null, { message: "Invalid concept occurrence" });
  }
  const rawExplanation = nullableString(r.explanation, "explanation");
  if (rawExplanation !== null && (!rawExplanation.trim() || rawExplanation.length > 600)) {
    throw new ApiError("parse", null, { message: "Invalid concept explanation" });
  }
  const explanation = rawExplanation;
  const expression = str(r.expression, "expression");
  const meaning = str(r.contextual_meaning, "contextual_meaning");
  if (expression.length > 500 || meaning.length > 600) {
    throw new ApiError("parse", null, { message: "Invalid concept text length" });
  }
  return {
    library_item_id: uuid(r.library_item_id),
    learning_object_id: uuid(r.learning_object_id),
    expression,
    occurrence_text: occurrence,
    source_segment_text: source,
    start_codepoint: start,
    end_codepoint: end,
    learning_language_code: str(r.learning_language_code, "learning_language_code"),
    support_language_code: str(r.support_language_code, "support_language_code"),
    contextual_meaning: meaning,
    explanation,
    ...parseMeaningSource(r),
  };
}

// An older backend omits both fields: its meanings are unverified. A "dictionary" meaning
// must carry its sense and licence credit, with https links only.
function parseMeaningSource(r: Record<string, unknown>): {
  meaning_provenance: MeaningProvenance;
  dictionary_sense: DictionarySenseView | null;
} {
  const provenance = r.meaning_provenance ?? "unverified";
  if (provenance === "unverified") {
    if (r.dictionary_sense != null) {
      throw new ApiError("parse", null, { message: "Invalid meaning provenance" });
    }
    return { meaning_provenance: "unverified", dictionary_sense: null };
  }
  if (provenance !== "dictionary") {
    throw new ApiError("parse", null, { message: "Invalid meaning provenance" });
  }
  const d = object(r.dictionary_sense, "Invalid dictionary sense");
  return {
    meaning_provenance: "dictionary",
    dictionary_sense: {
      headword: str(d.headword, "headword"),
      reading: optionalText(d.reading, "reading"),
      part_of_speech: optionalText(d.part_of_speech, "part_of_speech"),
      definition: str(d.definition, "definition"),
      source_name: str(d.source_name, "source_name"),
      source_url: httpsUrl(d.source_url, "source_url"),
      license_name: str(d.license_name, "license_name"),
      license_url: httpsUrl(d.license_url, "license_url"),
    },
  };
}

function optionalText(value: unknown, key: string): string | null {
  if (value == null) return null;
  return str(value, key);
}

function httpsUrl(value: unknown, key: string): string {
  const text = str(value, key);
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    throw new ApiError("parse", null, { message: `Invalid ${key}` });
  }
  if (url.protocol !== "https:") throw new ApiError("parse", null, { message: `Invalid ${key}` });
  return url.toString();
}

function object(value: unknown, message: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError("parse", null, { message });
  }
  return value as Record<string, unknown>;
}

function str(value: unknown, key: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new ApiError("parse", null, { message: `Invalid ${key}` });
  }
  return value;
}

function uuid(value: unknown): string {
  const v = str(value, "uuid");
  if (!UUID_RE.test(v)) throw new ApiError("parse", null, { message: "Invalid uuid" });
  return v;
}

function intOrNull(value: unknown, min: number): number | null {
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= min) return value;
  if (value === null) return null;
  throw new ApiError("parse", null, { message: "Invalid nullable integer" });
}

function nullableString(value: unknown, key: string): string | null {
  if (value === null) return null;
  if (typeof value === "string") return value;
  throw new ApiError("parse", null, { message: `Invalid ${key}` });
}

const LOOKUP_PROVENANCE = ["translated_from_sense", "ai_unverified", "dictionary_only", "unavailable"] as const;

export function parseWordLookupView(raw: unknown, segmentText: string): WordLookupView {
  const r = object(raw, "Invalid lookup response");
  const count = [...segmentText].length;
  const at = (value: unknown) => {
    if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > count) {
      throw new ApiError("parse", null, { message: "Invalid lookup span" });
    }
    return value;
  };
  const [selectionStart, selectionEnd, unitStart, unitEnd] = [
    at(r.selection_start), at(r.selection_end), at(r.unit_start), at(r.unit_end),
  ];
  if (selectionEnd <= selectionStart || unitEnd <= unitStart || unitStart > selectionStart || unitEnd < selectionEnd) {
    throw new ApiError("parse", null, { message: "Invalid lookup span" });
  }
  const unitText = str(r.unit_text, "unit_text");
  if ([...segmentText].slice(unitStart, unitEnd).join("") !== unitText) {
    throw new ApiError("parse", null, { message: "Invalid lookup unit" });
  }
  if (r.unit_kind !== "word" && r.unit_kind !== "phrase") {
    throw new ApiError("parse", null, { message: "Invalid lookup unit kind" });
  }
  if (typeof r.selection_is_part !== "boolean") {
    throw new ApiError("parse", null, { message: "Invalid lookup flag" });
  }
  const provenance = r.meaning_provenance;
  if (typeof provenance !== "string" || !(LOOKUP_PROVENANCE as readonly string[]).includes(provenance)) {
    throw new ApiError("parse", null, { message: "Invalid lookup provenance" });
  }
  const meaning = nullableString(r.meaning, "meaning");
  if ((provenance === "translated_from_sense" || provenance === "ai_unverified") && meaning === null) {
    throw new ApiError("parse", null, { message: "Lookup meaning missing" });
  }
  const gloss = nullableString(r.dictionary_gloss, "dictionary_gloss");
  let source: LookupSourceView | null = null;
  if (r.source != null) {
    const s = object(r.source, "Invalid lookup source");
    source = {
      name: str(s.name, "source.name"),
      license_name: str(s.license_name, "source.license_name"),
      license_url: httpsUrl(s.license_url, "source.license_url"),
      entry_url: httpsUrl(s.entry_url, "source.entry_url"),
    };
  }
  // A dictionary credit always comes with the dictionary text it credits.
  if ((source === null) !== (gloss === null)) {
    throw new ApiError("parse", null, { message: "Invalid lookup source" });
  }
  return {
    segment_id: uuid(r.segment_id),
    selection_start: selectionStart,
    selection_end: selectionEnd,
    unit_start: unitStart,
    unit_end: unitEnd,
    unit_text: unitText,
    unit_kind: r.unit_kind,
    selection_is_part: r.selection_is_part,
    headword: nullableString(r.headword, "headword"),
    reading: nullableString(r.reading, "reading"),
    part_of_speech: nullableString(r.part_of_speech, "part_of_speech"),
    dictionary_gloss: gloss,
    sense_id: nullableString(r.sense_id, "sense_id"),
    meaning,
    note: nullableString(r.note, "note"),
    // Absent from older servers: an explanation without them still shows.
    pattern: Array.isArray(r.pattern) ? r.pattern.filter((part): part is string => typeof part === "string" && part.length > 0).slice(0, 6) : [],
    pattern_explanation: r.pattern_explanation == null ? null : nullableString(r.pattern_explanation, "pattern_explanation"),
    examples: Array.isArray(r.examples) ? r.examples.flatMap((item) => {
      const example = item && typeof item === "object" ? item as Record<string, unknown> : null;
      return example && typeof example.text === "string" && typeof example.translation === "string" && example.text
        ? [{ text: example.text, translation: example.translation }] : [];
    }).slice(0, 2) : [],
    context_before: r.context_before == null ? null : nullableString(r.context_before, "context_before"),
    context_after: r.context_after == null ? null : nullableString(r.context_after, "context_after"),
    meaning_provenance: provenance as LookupProvenance,
    level: nullableString(r.level, "level"),
    source,
  };
}
