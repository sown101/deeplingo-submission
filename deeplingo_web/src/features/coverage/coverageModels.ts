import { ApiError } from "../../lib/api/errors";

// L1c: how much of a video the learner is likely to follow. Always an estimate made by the server
// from the transcript and the dictionary; the client only shows it.
export type CoverageLabel = "suitable" | "challenging" | "hard";

// One video in the learner's recommendation list; everything but the id is null while no word
// profile exists yet for the video.
export interface CoverageSummary {
  libraryItemId: string;
  languageCode: string | null;
  coverage: number | null;
  label: CoverageLabel | null;
  speechRateWpm: number | null;
  wordsToTarget: number | null;
}

export const LABEL_TEXT: Record<CoverageLabel, string> = {
  suitable: "Comfortable",
  challenging: "Challenging",
  hard: "Hard",
};

function fail(): never {
  throw new ApiError("parse", null, { message: "Invalid coverage response" });
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string") fail();
  return value;
}

function optionalText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function num(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) fail();
  return value;
}

function optionalNum(value: unknown): number | null {
  return value === null || value === undefined ? null : num(value);
}

function label(value: unknown): CoverageLabel {
  if (value !== "suitable" && value !== "challenging" && value !== "hard") fail();
  return value;
}

export function parseCoverageSummaries(raw: unknown): CoverageSummary[] {
  if (!Array.isArray(raw)) fail();
  return raw.map((item) => {
    const r = record(item);
    return {
      libraryItemId: text(r.library_item_id),
      languageCode: optionalText(r.language_code),
      coverage: optionalNum(r.coverage),
      label: r.label === null || r.label === undefined ? null : label(r.label),
      speechRateWpm: optionalNum(r.speech_rate_wpm),
      wordsToTarget: optionalNum(r.words_to_target),
    };
  });
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}
