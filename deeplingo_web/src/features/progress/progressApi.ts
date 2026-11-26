import type { ApiClient } from "../../lib/api/apiClient";
import { ApiError } from "../../lib/api/errors";

export class ProgressApi {
  constructor(private readonly client: ApiClient) {}

  /** The learner's progress from one endpoint, for one language or all of them. */
  async loadProgress(language?: string): Promise<Progress> {
    const query: Record<string, string> = { utc_offset_minutes: String(localUtcOffsetMinutes()) };
    if (language) query.language = language;
    return parseProgress(await this.client.get<unknown>("/learner/me/progress", { query }));
  }
}

/** Days with at least one log row; `attempts` is the number of rows that day. */
export interface ActivityDay { date: string; attempts: number }
export interface ActivityCalendar { days: ActivityDay[]; active_days: number; current_streak_days: number }

export interface Deck { language_code: string; total: number; due: number; new: number; learning: number; review: number; relearning: number }
export interface KindAccuracy { kind: string; attempts: number; correct: number; accuracy: number }
/** Average of each score over the practices of one day; null when none was recorded (prosody is English only). */
export interface PronunciationDay { date: string; pronunciation: number | null; accuracy: number | null; fluency: number | null;
  completeness: number | null; prosody: number | null; sessions: number }
export interface SpeakingWeek { week_start: string; minutes: number }

export interface Progress {
  language: string | null;
  languages: string[];
  streak: { current: number; longest: number; active_days: number };
  calendar: ActivityCalendar;
  cards: Deck[];
  accuracy: KindAccuracy[];
  pronunciation: PronunciationDay[];
  weak_words: string[];
  grammar: { learned: number; done_correctly: number };
  regions_completed: number;
  speaking: { sessions: number; minutes: number; weeks: SpeakingWeek[] };
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const bad = (message: string) => new ApiError("parse", null, { message });

function record(raw: unknown, message = "Invalid progress"): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw bad(message);
  return raw as Record<string, unknown>;
}

function num(value: unknown, message = "Invalid progress number"): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw bad(message);
  return value;
}

function score(value: unknown): number | null {
  return value === null || value === undefined ? null : num(value, "Invalid progress score");
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw bad("Invalid progress list");
  return value;
}

function date(value: unknown): string {
  if (typeof value !== "string" || !DATE_RE.test(value)) throw bad("Invalid progress date");
  return value;
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value) throw bad("Invalid progress text");
  return value;
}

export function parseProgress(raw: unknown): Progress {
  const r = record(raw);
  const streak = record(r.streak);
  const grammar = record(r.grammar);
  const speaking = record(r.speaking);
  const days = list(r.heatmap).map(item => {
    const d = record(item);
    return { date: date(d.date), attempts: num(d.count) };
  });
  const current = num(streak.current);
  const active = num(streak.active_days);
  if (active !== days.filter(day => day.attempts > 0).length) throw bad("Inconsistent progress");
  return {
    language: r.language === null || r.language === undefined ? null : text(r.language),
    languages: list(r.languages).map(text),
    streak: { current, longest: num(streak.longest), active_days: active },
    calendar: { days, active_days: active, current_streak_days: current },
    cards: list(r.cards).map(item => {
      const d = record(item);
      return { language_code: text(d.language_code), total: num(d.total), due: num(d.due), new: num(d.new),
        learning: num(d.learning), review: num(d.review), relearning: num(d.relearning) };
    }),
    accuracy: list(r.accuracy).map(item => {
      const d = record(item);
      return { kind: text(d.kind), attempts: num(d.attempts), correct: num(d.correct), accuracy: num(d.accuracy) };
    }),
    pronunciation: list(r.pronunciation).map(item => {
      const d = record(item);
      return { date: date(d.date), pronunciation: score(d.pronunciation), accuracy: score(d.accuracy), fluency: score(d.fluency),
        completeness: score(d.completeness), prosody: score(d.prosody), sessions: num(d.sessions) };
    }),
    weak_words: list(r.weak_words).map(text),
    grammar: { learned: num(grammar.learned), done_correctly: num(grammar.done_correctly) },
    regions_completed: num(r.regions_completed),
    speaking: { sessions: num(speaking.sessions), minutes: num(speaking.minutes),
      weeks: list(speaking.weeks).map(item => { const d = record(item); return { week_start: date(d.week_start), minutes: num(d.minutes) }; }) },
  };
}

/** Minutes east of UTC for the browser, used only to bucket days for display. */
export function localUtcOffsetMinutes(): number {
  return -new Date().getTimezoneOffset();
}
