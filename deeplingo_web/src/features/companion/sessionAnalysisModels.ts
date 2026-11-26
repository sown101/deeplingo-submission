import { ApiError } from "../../lib/api/errors";

export type AnalysisStatus = "queued" | "processing" | "projecting" | "completed" | "failed" | "expired" | "unavailable";
export interface AnalysisReference { session_id: string; status: AnalysisStatus }
export interface SessionAnalysisView extends AnalysisReference {
  events: { concept_id: string; text: string; kind: "framed_use" | "spontaneous_use" }[];
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATUSES = new Set(["queued", "processing", "projecting", "completed", "failed", "expired", "unavailable"]);

export function parseAnalysisReference(raw: unknown): AnalysisReference | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const r = raw as Record<string, unknown>;
  return typeof r.session_id === "string" && UUID.test(r.session_id) && typeof r.status === "string" && STATUSES.has(r.status)
    ? { session_id: r.session_id, status: r.status as AnalysisStatus } : undefined;
}

export function parseSessionAnalysis(raw: unknown): SessionAnalysisView {
  const reference = parseAnalysisReference(raw), r = raw as Record<string, unknown>;
  const fail = (): never => { throw new ApiError("parse", null, { message: "Invalid speaking update" }); };
  if (!reference || !Array.isArray(r.events) || r.events.length > 12) return fail();
  const events = r.events.map((value) => {
    if (!value || typeof value !== "object") return fail();
    const item = value as Record<string, unknown>;
    if (typeof item.concept_id !== "string" || !UUID.test(item.concept_id) || typeof item.text !== "string"
      || !item.text.trim() || (item.kind !== "framed_use" && item.kind !== "spontaneous_use")) return fail();
    return { concept_id: item.concept_id, text: item.text, kind: item.kind } as SessionAnalysisView["events"][number];
  });
  return { ...reference, events };
}
