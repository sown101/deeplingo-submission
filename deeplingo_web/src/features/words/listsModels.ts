import { ApiError } from "../../lib/api/errors";
import { parseMyWord, type WordStatus } from "./wordsModels";

// L1b named word lists. The server resolves every pasted word; the client only sends text and
// the choice among meanings the server stored for a waiting line.

// The server reads at most this many lines per request; a longer paste is sent in batches.
export const MAX_BATCH_LINES = 50;

export interface ListSummary {
  id: string;
  languageCode: string;
  name: string;
  description: string | null;
  wordCount: number;
  waitingCount: number;
}

export interface ListWord {
  conceptId: string;
  text: string;
  gloss: string | null;
  status: WordStatus;
  rung: number;
  levelLabel: string | null;
  aboveLevel: boolean;
  reading: string | null;
  traditional: string | null;
  note: string | null;
  favorite: boolean;
}

export interface MeaningCandidate {
  entryId: string;
  senseId: string;
  headword: string;
  text: string;
  partOfSpeech: string | null;
}

export interface WaitingLine {
  id: string;
  text: string;
  gloss: string | null;
  resolution: "ambiguous" | "unresolved";
  candidates: MeaningCandidate[];
}

export interface ListDetail extends ListSummary {
  words: ListWord[];
  waiting: WaitingLine[];
}

export interface ImportReport {
  matched: number;
  ambiguous: number;
  unresolved: number;
  alreadyInList: number;
  duplicates: number;
  tooLong: number;
  overLimit: number;
  aboveLevel: number;
  listFull: boolean;
}

function fail(): never {
  throw new ApiError("parse", null, { message: "Invalid word list response" });
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
  if (value === null || value === undefined) return null;
  return text(value);
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) fail();
  return value;
}

export function parseListSummary(raw: unknown): ListSummary {
  const r = record(raw);
  return {
    id: text(r.id),
    languageCode: text(r.language_code),
    name: text(r.name),
    description: optionalText(r.description),
    wordCount: count(r.word_count),
    waitingCount: count(r.waiting_count),
  };
}

export function parseListSummaries(raw: unknown): ListSummary[] {
  if (!Array.isArray(raw)) fail();
  return raw.map(parseListSummary);
}

function parseListWord(raw: unknown): ListWord {
  const r = record(raw);
  // Reuse the My words parser for status/rung validation by giving it the fields it needs.
  const word = parseMyWord({
    concept_id: r.concept_id, language_code: "-", text: r.text, kind: "-", gloss: r.gloss, list: "saved",
    saved: true, status: r.status, rung: r.rung, level_label: r.level_label, above_level: r.above_level,
    reading: r.reading, traditional: r.traditional, note: r.note, favorite: r.favorite,
  });
  return {
    conceptId: word.conceptId, text: word.text, gloss: word.gloss, status: word.status, rung: word.rung,
    levelLabel: word.levelLabel, aboveLevel: word.aboveLevel, reading: word.reading, traditional: word.traditional,
    note: word.note, favorite: word.favorite,
  };
}

function parseCandidate(raw: unknown): MeaningCandidate {
  const r = record(raw);
  return {
    entryId: text(r.entry_id), senseId: text(r.sense_id), headword: text(r.headword), text: text(r.text),
    partOfSpeech: optionalText(r.part_of_speech),
  };
}

function parseWaitingLine(raw: unknown): WaitingLine {
  const r = record(raw);
  const resolution = r.resolution;
  if (resolution !== "ambiguous" && resolution !== "unresolved") fail();
  const candidates = r.candidates === undefined ? [] : r.candidates;
  if (!Array.isArray(candidates)) fail();
  return {
    id: text(r.id), text: text(r.text), gloss: optionalText(r.gloss), resolution, candidates: candidates.map(parseCandidate),
  };
}

export function parseListDetail(raw: unknown): ListDetail {
  const r = record(raw);
  if (!Array.isArray(r.words) || !Array.isArray(r.waiting)) fail();
  return { ...parseListSummary(raw), words: r.words.map(parseListWord), waiting: r.waiting.map(parseWaitingLine) };
}

export function parseListWordResult(raw: unknown): ListWord {
  return parseListWord(raw);
}

export function parseImportReport(raw: unknown): ImportReport {
  const r = record(raw);
  if (typeof r.list_full !== "boolean") fail();
  return {
    matched: count(r.matched), ambiguous: count(r.ambiguous), unresolved: count(r.unresolved),
    alreadyInList: count(r.already_in_list), duplicates: count(r.duplicates), tooLong: count(r.too_long),
    overLimit: count(r.over_limit), aboveLevel: count(r.above_level), listFull: r.list_full,
  };
}

export function emptyReport(): ImportReport {
  return {
    matched: 0, ambiguous: 0, unresolved: 0, alreadyInList: 0, duplicates: 0, tooLong: 0, overLimit: 0,
    aboveLevel: 0, listFull: false,
  };
}

export function addReports(a: ImportReport, b: ImportReport): ImportReport {
  return {
    matched: a.matched + b.matched, ambiguous: a.ambiguous + b.ambiguous, unresolved: a.unresolved + b.unresolved,
    alreadyInList: a.alreadyInList + b.alreadyInList, duplicates: a.duplicates + b.duplicates,
    tooLong: a.tooLong + b.tooLong, overLimit: a.overLimit + b.overLimit, aboveLevel: a.aboveLevel + b.aboveLevel,
    listFull: a.listFull || b.listFull,
  };
}

// Splits pasted text into requests of at most `size` lines. Blank lines are dropped here so a
// batch is never mostly empty; every other rule (quotes, comments, duplicates) stays with the server.
export function splitIntoBatches(raw: string, size = MAX_BATCH_LINES): string[] {
  const lines = raw.split(/\r?\n/).filter((line) => line.trim() !== "");
  const batches: string[] = [];
  for (let start = 0; start < lines.length; start += size) batches.push(lines.slice(start, start + size).join("\n"));
  return batches;
}

// The error code of a list request, when the server sent one.
export function listErrorCode(error: unknown): string | null {
  return error instanceof ApiError && typeof error.detail.code === "string" ? error.detail.code : null;
}
