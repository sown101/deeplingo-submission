import { ApiError } from "../../../lib/api/errors";

// Study parts of a video, cut by AI once per transcript on the server (2026-11-05). "fallback" means
// the model was unavailable and the server cut by sentence count; the parts work the same way.
export interface VideoPart {
  start_segment_id: string;
  end_segment_id: string;
  start_ms: number;
  end_ms: number;
  segment_count: number;
  title: string | null;
}

export interface VideoParts {
  transcript_id: string;
  source: "ai" | "fallback";
  parts: VideoPart[];
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function fail(): never {
  throw new ApiError("parse", null, { message: "Invalid video parts" });
}

function count(value: unknown, min: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < min) fail();
  return value;
}

function id(value: unknown): string {
  if (typeof value !== "string" || !UUID_RE.test(value)) fail();
  return value;
}

export function parseVideoParts(raw: unknown): VideoParts {
  if (!raw || typeof raw !== "object") fail();
  const r = raw as Record<string, unknown>;
  if ((r.source !== "ai" && r.source !== "fallback") || !Array.isArray(r.parts) || r.parts.length === 0) fail();
  const parts = r.parts.map((item): VideoPart => {
    if (!item || typeof item !== "object") fail();
    const p = item as Record<string, unknown>;
    const title = p.title === null || p.title === undefined ? null : typeof p.title === "string" ? p.title.trim() || null : fail();
    const start_ms = count(p.start_ms, 0), end_ms = count(p.end_ms, 1);
    if (end_ms <= start_ms) fail();
    return { start_segment_id: id(p.start_segment_id), end_segment_id: id(p.end_segment_id), start_ms, end_ms,
             segment_count: count(p.segment_count, 1), title };
  });
  return { transcript_id: id(r.transcript_id), source: r.source, parts };
}

/** The part to open first: the one holding the saved position, else the first part after it, else the first. */
export function partAt(parts: VideoPart[], positionMs: number | null | undefined): VideoPart | undefined {
  const at = positionMs ?? 0;
  return parts.find(part => at >= part.start_ms && at < part.end_ms) ?? parts.find(part => part.start_ms >= at) ?? parts[0];
}

/** The part right after the learner's current region, by the AI cut. */
export function partAfter(parts: VideoPart[], region: { end_segment_id: string } | null | undefined): VideoPart | null {
  if (!region) return null;
  const index = parts.findIndex(part => part.end_segment_id === region.end_segment_id);
  return index >= 0 ? parts[index + 1] ?? null : null;
}
