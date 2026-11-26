import { ApiError } from "../../lib/api/errors";

// Learner-facing speaking-practice projections. Scores are server
// practice estimates for display only; nothing here is learner state.

export type FeedbackBand = "excellent" | "good" | "fair" | "retry";
export type WordErrorType =
  | "none" | "mispronunciation" | "omission" | "insertion"
  | "unexpected_break" | "missing_break" | "monotone" | "other";

export interface SpeakingScores {
  pronunciation: number;
  accuracy: number;
  fluency: number;
  completeness: number;
  prosody: number | null;
}

export interface SpeakingWord {
  word: string;
  accuracy: number;
  error_type: WordErrorType;
  phonemes: { phoneme: string; accuracy: number }[];
}

export interface ShadowingAssessment {
  segment_id: string;
  reference_text: string;
  recognized_text: string;
  band: FeedbackBand;
  scores: SpeakingScores;
  words: SpeakingWord[];
  attempt_duration_ms: number;
  reference_duration_ms: number;
  spoken_duration_ms: number | null;
}

const BANDS = ["excellent", "good", "fair", "retry"] as const;
const ERROR_TYPES = [
  "none", "mispronunciation", "omission", "insertion", "unexpected_break", "missing_break", "monotone", "other",
] as const;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function fail(message: string): never {
  throw new ApiError("parse", null, { message });
}

function obj(value: unknown, what: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(`Invalid ${what}`);
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && value.trim().length === 0)) fail(`Invalid ${what}`);
  return value;
}

function int(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) fail(`Invalid ${what}`);
  return value;
}

function nullableInt(value: unknown, what: string): number | null {
  return value === null || value === undefined ? null : int(value, what);
}

function score(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 100) fail(`Invalid ${what}`);
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) fail(`Invalid ${what}`);
  return value as T;
}

function list<T>(value: unknown, what: string, item: (entry: unknown) => T): T[] {
  if (!Array.isArray(value)) fail(`Invalid ${what}`);
  return value.map(item);
}

export function parseScores(raw: unknown): SpeakingScores {
  const r = obj(raw, "scores");
  return {
    pronunciation: score(r.pronunciation, "pronunciation"),
    accuracy: score(r.accuracy, "accuracy"),
    fluency: score(r.fluency, "fluency"),
    completeness: score(r.completeness, "completeness"),
    prosody: r.prosody === null || r.prosody === undefined ? null : score(r.prosody, "prosody"),
  };
}

export function parseShadowingAssessment(raw: unknown, expectedSegmentId: string): ShadowingAssessment {
  const r = obj(raw, "shadowing assessment");
  const segmentId = text(r.segment_id, "segment_id");
  if (!UUID_RE.test(segmentId) || segmentId !== expectedSegmentId) fail("Mismatched shadowing segment");
  return {
    segment_id: segmentId,
    reference_text: text(r.reference_text, "reference_text"),
    recognized_text: text(r.recognized_text, "recognized_text", true),
    band: oneOf(r.band, BANDS, "band"),
    scores: parseScores(r.scores),
    words: list(r.words, "words", (entry) => {
      const w = obj(entry, "word");
      return {
        word: text(w.word, "word"),
        accuracy: score(w.accuracy, "word accuracy"),
        error_type: oneOf(w.error_type, ERROR_TYPES, "error_type"),
        phonemes: list(w.phonemes, "phonemes", (item) => {
          const p = obj(item, "phoneme");
          return { phoneme: text(p.phoneme, "phoneme"), accuracy: score(p.accuracy, "phoneme accuracy") };
        }),
      };
    }),
    attempt_duration_ms: int(r.attempt_duration_ms, "attempt_duration_ms"),
    reference_duration_ms: int(r.reference_duration_ms, "reference_duration_ms"),
    spoken_duration_ms: nullableInt(r.spoken_duration_ms, "spoken_duration_ms"),
  };
}
