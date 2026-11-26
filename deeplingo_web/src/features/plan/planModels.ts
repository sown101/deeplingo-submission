import { ApiError } from "../../lib/api/errors";

// Plan items as the companion's follow-up proposals. The backend chooses them; the client
// shows them and opens the existing screen for a chosen one. The web shows no daily plan (M1 Q1).

export type PlanItemKind = "review" | "conversation" | "video_practice" | "my_words" | "add_video";
export type PlanItemStatus = "open" | "accepted" | "dismissed";

export interface PlanItem {
  id: string;
  kind: PlanItemKind;
  status: PlanItemStatus;
  minutes: number;
  reason: string;
  item_count: number | null;
  library_item_id: string | null;
  video_title: string | null;
  companion_entry: "video" | "review" | "home" | null;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KINDS = ["review", "conversation", "video_practice", "my_words", "add_video"] as const;
const STATUSES = ["open", "accepted", "dismissed"] as const;
const ENTRIES = ["video", "review", "home"] as const;

function fail(message: string): never {
  throw new ApiError("parse", null, { message });
}

function obj(value: unknown, what: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(`Invalid ${what}`);
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string" || value.trim().length === 0) fail(`Invalid ${what}`);
  return value;
}

function uuid(value: unknown, what: string): string {
  const v = text(value, what);
  if (!UUID_RE.test(v)) fail(`Invalid ${what}`);
  return v;
}

function count(value: unknown, what: string, min = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min) fail(`Invalid ${what}`);
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) fail(`Invalid ${what}`);
  return value as T;
}

export function parsePlanItem(raw: unknown): PlanItem {
  const r = obj(raw, "plan item");
  const kind = oneOf(r.kind, KINDS, "plan item kind");
  const library = r.library_item_id == null ? null : uuid(r.library_item_id, "library item");
  const entry = r.companion_entry == null ? null : oneOf(r.companion_entry, ENTRIES, "companion entry");
  // The same shape rules as the backend: a conversation names its entry, and a video target
  // always comes with the learner's library item.
  if ((kind === "conversation") !== (entry !== null)) fail("Invalid conversation entry");
  if ((kind === "video_practice" || entry === "video") !== (library !== null)) fail("Invalid video target");
  return {
    id: uuid(r.id, "plan item id"),
    kind,
    status: oneOf(r.status, STATUSES, "plan item status"),
    minutes: count(r.minutes, "minutes", 1),
    reason: text(r.reason, "reason"),
    item_count: r.item_count == null ? null : count(r.item_count, "item count"),
    library_item_id: library,
    video_title: r.video_title == null ? null : text(r.video_title, "video title"),
    companion_entry: entry,
  };
}

/** Where an accepted proposal leads: existing screens only. */
export function planItemPath(item: PlanItem): string {
  switch (item.kind) {
    case "review":
      return "/review/quick"; // M1 D1: Quick review is the review on web
    case "conversation":
      return item.companion_entry === "video" && item.library_item_id
        ? `/agent?mode=voice&entry=video&item=${item.library_item_id}`
        : `/agent?mode=voice&entry=${item.companion_entry === "review" ? "review" : "home"}`;
    case "video_practice":
      return `/library/videos/${item.library_item_id}/watch`; // the old practice page is gone; Watch has the tools
    case "my_words":
      return "/words";
    case "add_video":
      return "/home"; // the link form is on Home
  }
}

/** Yesterday's speaking as counts and the names of the learner's own saved words (FR-3.10). */
export interface YesterdaySpeaking {
  sessions: number;
  minutes: number;
  turns: number;
  reuse_words: string[];
}

export interface StudyPlan {
  plan_id: string;
  day: string;
  language_code: string;
  intro: string;
  items: PlanItem[];
  yesterday: YesterdaySpeaking | null;
}

function parseYesterday(raw: unknown): YesterdaySpeaking | null {
  if (raw == null) return null;
  const r = obj(raw, "yesterday");
  const words = r.reuse_words;
  if (!Array.isArray(words)) fail("Invalid yesterday words");
  return {
    sessions: count(r.sessions, "yesterday sessions"),
    minutes: count(r.minutes, "yesterday minutes"),
    turns: count(r.turns, "yesterday turns"),
    reuse_words: words.filter((word): word is string => typeof word === "string" && word.trim().length > 0 && word.length <= 60).slice(0, 6),
  };
}

/** Today's plan as the server stored it: a short greeting and up to three suggestions. */
export function parseStudyPlan(raw: unknown): StudyPlan {
  const r = obj(raw, "study plan");
  if (!Array.isArray(r.items)) fail("Invalid plan items");
  return {
    plan_id: text(r.plan_id, "plan id"),
    day: text(r.day, "plan day"),
    language_code: text(r.language_code, "plan language"),
    intro: text(r.intro, "plan intro"),
    items: r.items.map(parsePlanItem),
    yesterday: parseYesterday(r.yesterday),
  };
}

/** The learner's local calendar date, which names today's plan. */
export function localDay(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
