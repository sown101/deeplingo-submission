// The body of GET /learner/me/progress for the mocked browser tests.
export type Heat = { date: string; count: number };

export function progressBody(overrides: Record<string, unknown> = {}) {
  const heatmap = (overrides.heatmap as Heat[] | undefined) ?? [];
  return {
    language: null, languages: ["en"], utc_offset_minutes: 0, window_days: 365,
    streak: { current: heatmap.length ? 3 : 0, longest: heatmap.length ? 3 : 0, active_days: heatmap.length },
    heatmap,
    cards: [], accuracy: [], pronunciation: [], weak_words: [], grammar: { learned: 0, done_correctly: 0 },
    regions_completed: 0, speaking: { sessions: 0, minutes: 0, weeks: [] },
    ...overrides,
  };
}

/** `count` days ending today (local), every other day active. */
export function recentHeat(days: number): Heat[] {
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(); date.setDate(date.getDate() - (days - 1 - index));
    const local = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    return { date: local, count: index % 3 ? index % 7 + 1 : 0 };
  }).filter(day => day.count > 0);
}
