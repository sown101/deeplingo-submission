import { ApiError } from "../../../lib/api/errors";
import type { TranscriptSegmentView } from "../../../lib/api/dto";

// M1 S1 video workspace: where the learner is in one Library video. The server resolves the
// region against its current transcript version; the client only selects segment IDs.

// M1 S2: readiness of the region's learning content (global, server-prepared). "unavailable"
// means the server could not ask or read it just now; it is never a learner result.
export const REGION_PREPARATION_STATES = [
  "pending",
  "processing",
  "ready",
  "no_content",
  "failed",
  "budget_exhausted",
  "transcript_unavailable",
  "region_unavailable",
  "unavailable",
  // M1 S7b: preparation is at its shared limit; asking again later is not charged.
  "busy",
] as const;
export type RegionPreparationState = (typeof REGION_PREPARATION_STATES)[number];

export interface RegionPreparationView {
  status: RegionPreparationState;
  usable_count: number;
  retryable: boolean;
  reset_at: string | null;
  // M1 S6: whether the part's comprehension questions exist (null until prepared).
  questions_status: "ready" | "none" | "failed" | null;
}

export interface StudyRegionView {
  transcript_id: string;
  start_segment_id: string;
  end_segment_id: string;
  start_ms: number;
  end_ms: number;
  segment_count: number;
  preparation: RegionPreparationView | null;
}

// The id the server logs a study part under: its first and last sentence (same text on both sides).
export function regionIdOf(region: { start_segment_id: string; end_segment_id: string }): string {
  return `${region.start_segment_id.toLowerCase()}_${region.end_segment_id.toLowerCase()}`;
}

const SEGMENT_ID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const REGION_PARAM = new RegExp(`^(${SEGMENT_ID})_(${SEGMENT_ID})$`);

/** A region named in a link (`?region=<first sentence>_<last sentence>`, as an agent card builds it), or null. */
export function regionFromParam(raw: string | null): { start_segment_id: string; end_segment_id: string } | null {
  const match = REGION_PARAM.exec((raw ?? "").toLowerCase());
  return match ? { start_segment_id: match[1], end_segment_id: match[2] } : null;
}

// Still being prepared on the server: worth reading again shortly.
export function preparationInProgress(preparation: RegionPreparationView | null | undefined): boolean {
  return preparation?.status === "pending" || preparation?.status === "processing";
}

export interface VideoWorkspaceView {
  library_item_id: string;
  position_ms: number | null;
  region: StudyRegionView | null;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function fail(): never {
  throw new ApiError("parse", null, { message: "Invalid workspace response" });
}

function uuid(value: unknown): string {
  return typeof value === "string" && UUID_RE.test(value) ? value : fail();
}

function int(value: unknown, min: number): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= min ? value : fail();
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : fail();
}

function parsePreparation(raw: unknown): RegionPreparationView | null {
  if (raw === null || raw === undefined) return null;
  const r = record(raw);
  const status = REGION_PREPARATION_STATES.find((state) => state === r.status) ?? fail();
  if (typeof r.retryable !== "boolean") fail();
  const resetAt = r.reset_at === null || r.reset_at === undefined ? null : r.reset_at;
  if (resetAt !== null && (typeof resetAt !== "string" || Number.isNaN(Date.parse(resetAt)))) fail();
  const questions = r.questions_status ?? null;
  if (questions !== null && questions !== "ready" && questions !== "none" && questions !== "failed") fail();
  return {
    status,
    usable_count: int(r.usable_count, 0),
    retryable: r.retryable,
    reset_at: resetAt as string | null,
    questions_status: questions,
  };
}

export function parseRegion(raw: unknown): StudyRegionView | null {
  if (raw === null || raw === undefined) return null;
  const r = record(raw);
  const region = {
    transcript_id: uuid(r.transcript_id),
    start_segment_id: uuid(r.start_segment_id),
    end_segment_id: uuid(r.end_segment_id),
    start_ms: int(r.start_ms, 0),
    end_ms: int(r.end_ms, 1),
    segment_count: int(r.segment_count, 1),
    preparation: parsePreparation(r.preparation),
  };
  return region.end_ms > region.start_ms ? region : fail();
}

// A response for a different Library item is never applied to this one.
export function parseVideoWorkspace(raw: unknown, libraryItemId: string): VideoWorkspaceView {
  const r = record(raw);
  const id = uuid(r.library_item_id);
  if (id.toLowerCase() !== libraryItemId.toLowerCase()) fail();
  return {
    library_item_id: id,
    position_ms: r.position_ms === null || r.position_ms === undefined ? null : int(r.position_ms, 0),
    region: parseRegion(r.region),
  };
}

// The region's sentences in display order; empty when this transcript does not hold it.
export function regionSegments(
  segments: TranscriptSegmentView[],
  region: StudyRegionView | null,
): TranscriptSegmentView[] {
  if (!region) return [];
  const start = segments.findIndex((segment) => segment.segment_id === region.start_segment_id);
  const end = segments.findIndex((segment) => segment.segment_id === region.end_segment_id);
  return start >= 0 && end >= start ? segments.slice(start, end + 1) : [];
}

export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${String(minutes).padStart(2, "0")}:${seconds}`;
}
