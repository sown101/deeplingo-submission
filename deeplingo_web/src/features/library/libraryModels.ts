import { ApiError } from "../../lib/api/errors";
import type {
  FailureCode,
  LearningPreparationStatus,
  LibraryVideoDetail,
  LibraryVideoSummary,
  ProcessingStatus,
} from "../../lib/api/dto";

const PROCESSING: readonly string[] = ["pending", "processing", "ready", "failed"];
const LEARNING: readonly string[] = [
  "not_started",
  "processing",
  "ready",
  "no_content",
  "failed",
];
const FAILURES: readonly string[] = [
  "invalid_video_url",
  "video_unavailable",
  "transcript_unavailable",
  "unsupported_content",
  "processing_failed",
];

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseLibraryVideoSummary(raw: unknown): LibraryVideoSummary {
  const r = expectObject(raw, "Invalid library video summary");
  const processing = oneOf(r.processing_status, PROCESSING) as ProcessingStatus | null;
  const learning = oneOf(r.learning_status, LEARNING);
  if (!processing || !learning) {
    throw new ApiError("parse", null, { message: "Invalid library video summary" });
  }
  const failure = parseFailure(r.failure);
  if ((processing === "failed") !== (failure !== null)) {
    throw new ApiError("parse", null, { message: "Inconsistent library processing failure" });
  }
  return {
    library_item_id: requireUuid(r.library_item_id),
    video_id: requireUuid(r.video_id),
    title: expectString(r.title),
    thumbnail_url: expectStringOrNull(r.thumbnail_url),
    duration_ms: expectIntOrNull(r.duration_ms, 0),
    source: expectString(r.source),
    processing_status: processing,
    learning_status: learning as LearningPreparationStatus,
    learning_object_count: expectInt(r.learning_object_count, 0),
    learning_prepared_language_code: expectStringOrNull(r.learning_prepared_language_code),
    language_code: expectString(r.language_code),
    added_at: expectString(r.added_at),
    failure,
  };
}

export function parseLibraryVideoDetail(raw: unknown): LibraryVideoDetail {
  const summary = parseLibraryVideoSummary(raw);
  const r = expectObject(raw, "Invalid library video detail");
  if (typeof r.transcript_available !== "boolean") {
    throw new ApiError("parse", null, { message: "Invalid transcript_available" });
  }
  return {
    ...summary,
    description: expectStringOrNull(r.description),
    transcript_available: r.transcript_available,
  };
}

function parseFailure(value: unknown): LibraryVideoSummary["failure"] {
  if (value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError("parse", null, { message: "Invalid library failure" });
  }
  const f = value as Record<string, unknown>;
  const code = oneOf(f.code, FAILURES) as FailureCode | null;
  if (!code || typeof f.retryable !== "boolean" || typeof f.message !== "string") {
    throw new ApiError("parse", null, { message: "Invalid library failure" });
  }
  return {
    code,
    retryable: f.retryable,
    message: f.message,
  };
}

function expectObject(value: unknown, message: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError("parse", null, { message });
  }
  return value as Record<string, unknown>;
}

function expectString(value: unknown, key = "field"): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new ApiError("parse", null, { message: `Invalid ${key}` });
  }
  return value;
}

function expectStringOrNull(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value === "string") return value;
  throw new ApiError("parse", null, { message: "Invalid nullable string" });
}

function expectInt(value: unknown, min: number): number {
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= min) return value;
  throw new ApiError("parse", null, { message: "Invalid non-negative integer" });
}

function expectIntOrNull(value: unknown, min: number): number | null {
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= min) return value;
  if (value === null) return null;
  throw new ApiError("parse", null, { message: "Invalid nullable integer" });
}

function oneOf(value: unknown, allowed: readonly string[]): string | null {
  return typeof value === "string" && allowed.includes(value) ? value : null;
}

function requireUuid(value: unknown): string {
  const v = expectString(value, "uuid");
  if (!UUID_RE.test(v)) throw new ApiError("parse", null, { message: "Invalid uuid" });
  return v;
}
