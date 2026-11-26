import { ApiError } from "../../../lib/api/errors";
import type { Translate } from "../../../i18n/i18n";

// What the learner did in one study part, summed by the server from their learning log (PRD 8.10).
// The client never computes a score: it shows these numbers.
export interface RegionResult {
  region_id: string;
  dictation_attempts: number;
  dictation_sentences: number;
  dictation_accuracy: number | null;
  shadowing_attempts: number;
  shadowing_sentences: number;
  shadowing_average: number | null;
  questions_answered: number;
  questions_correct: number;
  lookups: number;
  words_saved: number;
  practised: boolean;
}

function fail(): never {
  throw new ApiError("parse", null, { message: "Invalid region result" });
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : fail();
}

function score(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  return typeof value === "number" && value >= 0 && value <= 100 ? value : fail();
}

// A result for another part is never shown for this one.
export function parseRegionResult(raw: unknown, regionId: string): RegionResult {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) fail();
  const r = raw as Record<string, unknown>;
  if (r.region_id !== regionId || typeof r.practised !== "boolean") fail();
  return {
    region_id: regionId,
    dictation_attempts: count(r.dictation_attempts), dictation_sentences: count(r.dictation_sentences),
    dictation_accuracy: score(r.dictation_accuracy),
    shadowing_attempts: count(r.shadowing_attempts), shadowing_sentences: count(r.shadowing_sentences),
    shadowing_average: score(r.shadowing_average),
    questions_answered: count(r.questions_answered), questions_correct: count(r.questions_correct),
    lookups: count(r.lookups), words_saved: count(r.words_saved), practised: r.practised,
  };
}

export interface ResultLine { label: string; value: string }

// One line per thing practised, in the language the learner reads; nothing for what was not used.
export function resultLines(result: RegionResult, t: Translate): ResultLine[] {
  const lines: ResultLine[] = [];
  if (result.dictation_attempts > 0) {
    lines.push({ label: t("Dictation"), value: result.dictation_accuracy === null
      ? t("{n} attempts", { n: result.dictation_attempts })
      : t("{pct}% of words right, {n} attempts", { pct: Math.round(result.dictation_accuracy), n: result.dictation_attempts }) });
  }
  if (result.shadowing_attempts > 0) {
    lines.push({ label: t("Shadowing"), value: result.shadowing_average === null
      ? t("{n} attempts", { n: result.shadowing_attempts })
      : t("Average score {score}, {n} attempts", { score: Math.round(result.shadowing_average), n: result.shadowing_attempts }) });
  }
  if (result.questions_answered > 0) {
    lines.push({ label: t("Questions"), value: t("{right} of {answered} right", { right: result.questions_correct, answered: result.questions_answered }) });
  }
  if (result.words_saved > 0) lines.push({ label: t("New words saved"), value: String(result.words_saved) });
  if (result.lookups > 0) lines.push({ label: t("Looked up"), value: String(result.lookups) });
  return lines;
}
