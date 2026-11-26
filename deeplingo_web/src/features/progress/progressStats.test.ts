import { describe, expect, it } from "vitest";
import { parseProgress } from "./progressApi";

export const PROGRESS = {
  language: null,
  languages: ["en", "zh"],
  utc_offset_minutes: 420,
  window_days: 365,
  streak: { current: 1, longest: 2, active_days: 2 },
  heatmap: [{ date: "2026-10-13", count: 2 }, { date: "2026-10-14", count: 3 }],
  cards: [{ language_code: "en", total: 5, due: 2, new: 1, learning: 1, review: 2, relearning: 1 }],
  accuracy: [{ kind: "choice", attempts: 4, correct: 3, accuracy: 75 }],
  pronunciation: [{ date: "2026-10-14", pronunciation: 80.5, accuracy: 70, fluency: 90, completeness: 100, prosody: null, sessions: 2 }],
  weak_words: ["water"],
  grammar: { learned: 2, done_correctly: 1 },
  regions_completed: 3,
  speaking: { sessions: 2, minutes: 4.5, weeks: [{ week_start: "2026-10-12", minutes: 4.5 }] },
};

describe("progress decoder", () => {
  it("accepts the server progress and builds the calendar the charts draw", () => {
    const progress = parseProgress(PROGRESS);
    expect(progress.calendar).toEqual({ days: [{ date: "2026-10-13", attempts: 2 }, { date: "2026-10-14", attempts: 3 }], active_days: 2, current_streak_days: 1 });
    expect(progress.languages).toEqual(["en", "zh"]);
    expect(progress.cards[0].review).toBe(2);
    expect(progress.pronunciation[0]).toMatchObject({ accuracy: 70, prosody: null, sessions: 2 });
    expect(progress.weak_words).toEqual(["water"]);
    expect(progress.speaking.weeks).toEqual([{ week_start: "2026-10-12", minutes: 4.5 }]);
  });

  it("rejects malformed or inconsistent progress", () => {
    expect(() => parseProgress({ ...PROGRESS, streak: { ...PROGRESS.streak, active_days: 5 } })).toThrow();
    expect(() => parseProgress({ ...PROGRESS, heatmap: [{ date: "yesterday", count: 1 }] })).toThrow();
    expect(() => parseProgress({ ...PROGRESS, heatmap: [{ date: "2026-10-14", count: -1 }] })).toThrow();
    expect(() => parseProgress({ ...PROGRESS, cards: [{ language_code: "en" }] })).toThrow();
    expect(() => parseProgress({ ...PROGRESS, pronunciation: [{ ...PROGRESS.pronunciation[0], accuracy: -1 }] })).toThrow();
    expect(() => parseProgress({ ...PROGRESS, speaking: { ...PROGRESS.speaking, weeks: [{ week_start: "Monday", minutes: 1 }] } })).toThrow();
    expect(() => parseProgress(null)).toThrow();
  });
});
