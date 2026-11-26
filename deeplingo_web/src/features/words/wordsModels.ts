import { ApiError } from "../../lib/api/errors";

// My words. The server resolves every Concept;
// the client only shows these views and sends selectors.
export type WordList = "saved";
// L1a: where a word is in the learner's plan.
export type WordStatus = "backlog" | "active" | "suspended";

// Self-declared scales; English and Chinese are never converted into each other.
export const DECLARED_LEVELS: Record<string, readonly string[]> = {
  en: ["A1", "A2", "A2+", "B1", "B1+", "B2", "B2+"],
  zh: ["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"],
};

// The usage ladder R0..R5: how far the learner got with a word.
export const RUNG_LABELS = ["Seen", "Recognised", "Recalled", "Used with a hint", "Used on your own", "Durable"] as const;

export interface MyWord {
  conceptId: string;
  languageCode: string;
  text: string;
  kind: string;
  gloss: string | null;
  list: WordList;
  saved: boolean;
  saveSource: "lookup" | "manual" | "occurrence" | "import" | null;
  addedAt: string | null;
  nextReviewAt: string | null;
  status: WordStatus;
  explicit: boolean;
  reading: string | null;
  traditional: string | null;
  note: string | null;
  favorite: boolean;
  priority: number;
  levelLabel: string | null;
  rung: number;
  aboveLevel: boolean;
}

export interface TargetSummary {
  backlog: number;
  active: number;
  suspended: number;
  activatedToday: number;
  dailyNewLimit: number;
  declaredLevel: string | null;
}

export interface MyWordsView {
  words: MyWord[];
  summary: TargetSummary | null;
}

export interface DictionarySense {
  senseId: string;
  text: string;
  partOfSpeech: string | null;
  reading: string | null;
  example: string | null;
  // The same sense in the support language; null when the server could not translate it.
  meaning: string | null;
}

export interface DictionaryEntryResult {
  entryId: string;
  headword: string;
  level: string | null;
  senses: DictionarySense[];
  sourceName: string | null;
  sourceLicense: string | null;
  sourceUrl: string | null;
}

function fail(): never {
  throw new ApiError("parse", null, { message: "Invalid words response" });
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

export function parseMyWord(raw: unknown): MyWord {
  const r = record(raw);
  const list = r.list;
  if (list !== "saved") fail();
  const source = r.save_source;
  if (source !== null && source !== undefined && source !== "lookup" && source !== "manual" && source !== "occurrence" && source !== "import") fail();
  if (typeof r.saved !== "boolean") fail();
  const status = r.status === undefined ? "active" : r.status;
  if (status !== "backlog" && status !== "active" && status !== "suspended") fail();
  const rung = r.rung === undefined ? 0 : r.rung;
  if (typeof rung !== "number" || !Number.isInteger(rung) || rung < 0 || rung > 5) fail();
  const priority = r.priority === undefined ? 0 : r.priority;
  if (typeof priority !== "number") fail();
  if (r.explicit !== undefined && typeof r.explicit !== "boolean") fail();
  if (r.above_level !== undefined && typeof r.above_level !== "boolean") fail();
  return {
    conceptId: text(r.concept_id),
    languageCode: text(r.language_code),
    text: text(r.text),
    kind: text(r.kind),
    gloss: optionalText(r.gloss),
    list,
    saved: r.saved,
    saveSource: (source ?? null) as MyWord["saveSource"],
    addedAt: optionalText(r.added_at),
    nextReviewAt: optionalText(r.next_review_at),
    status,
    explicit: r.explicit === undefined ? true : (r.explicit as boolean),
    priority,
    levelLabel: optionalText(r.level_label),
    rung,
    aboveLevel: r.above_level === true,
    reading: optionalText(r.reading),
    traditional: optionalText(r.traditional),
    note: optionalText(r.note),
    favorite: r.favorite === true,
  };
}

export function parseMyWords(raw: unknown): MyWord[] {
  const words = record(raw).words;
  if (!Array.isArray(words)) fail();
  return words.map(parseMyWord);
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) fail();
  return value;
}

export function parseTargetSummary(raw: unknown): TargetSummary | null {
  if (raw === null || raw === undefined) return null;
  const r = record(raw);
  return {
    backlog: count(r.backlog),
    active: count(r.active),
    suspended: count(r.suspended),
    activatedToday: count(r.activated_today),
    dailyNewLimit: count(r.daily_new_limit),
    declaredLevel: optionalText(r.declared_level),
  };
}

export function parseMyWordsView(raw: unknown): MyWordsView {
  return { words: parseMyWords(raw), summary: parseTargetSummary(record(raw).summary) };
}

// A save that needs one confirmation because the word is above the learner's declared level.
export interface AboveLevelNotice {
  level: string | null;
  declaredLevel: string | null;
}

export function aboveLevelNotice(error: unknown): AboveLevelNotice | null {
  if (!(error instanceof ApiError) || error.status !== 409 || error.detail.code !== "above_level") return null;
  const body = error.detail.raw;
  const detail = body && typeof body === "object" ? (body as Record<string, unknown>).detail : null;
  const d = detail && typeof detail === "object" ? (detail as Record<string, unknown>) : {};
  return {
    level: typeof d.level === "string" ? d.level : null,
    declaredLevel: typeof d.declared_level === "string" ? d.declared_level : null,
  };
}

export function parseDictionarySearch(raw: unknown): DictionaryEntryResult[] {
  if (!Array.isArray(raw)) fail();
  return raw.map((item) => {
    const r = record(item);
    if (!Array.isArray(r.senses)) fail();
    return {
      entryId: text(r.entry_id),
      headword: text(r.headword),
      level: optionalText(r.level),
      senses: r.senses.map((sense) => {
        const s = record(sense);
        return {
          senseId: text(s.sense_id),
          text: text(s.text),
          partOfSpeech: optionalText(s.part_of_speech),
          reading: optionalText(s.reading),
          example: optionalText(s.example),
          meaning: optionalText(s.meaning),
        };
      }),
      sourceName: optionalText(r.source_name),
      sourceLicense: optionalText(r.source_license),
      sourceUrl: optionalText(r.source_url),
      author: optionalText(r.author),
    };
  });
}

// Examples for a saved word. A dictionary example carries its source and
// licence; an AI-written one is always labelled as such.
export interface ExampleSentence {
  id: string;
  text: string;
  startCodepoint: number | null;
  endCodepoint: number | null;
  translation: string | null;
  sourceKind: "dictionary" | "generated" | "occurrence" | "corpus";
  aiGenerated: boolean;
  sourceName: string | null;
  licenseName: string | null;
  licenseUrl: string | null;
  sourceUrl: string | null;
  author: string | null;
}

function optionalNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "number") fail();
  return value;
}

export function parseExamples(raw: unknown): ExampleSentence[] {
  const examples = record(raw).examples;
  if (!Array.isArray(examples)) fail();
  return examples.map((item) => {
    const r = record(item);
    const kind = r.source_kind;
    if (kind !== "dictionary" && kind !== "generated" && kind !== "occurrence" && kind !== "corpus") fail();
    if (typeof r.ai_generated !== "boolean") fail();
    return {
      id: text(r.id),
      text: text(r.text),
      startCodepoint: optionalNumber(r.start_codepoint),
      endCodepoint: optionalNumber(r.end_codepoint),
      translation: optionalText(r.translation),
      sourceKind: kind,
      aiGenerated: r.ai_generated,
      sourceName: optionalText(r.source_name),
      licenseName: optionalText(r.license_name),
      licenseUrl: optionalText(r.license_url),
      sourceUrl: optionalText(r.source_url),
      author: optionalText(r.author),
    };
  });
}
