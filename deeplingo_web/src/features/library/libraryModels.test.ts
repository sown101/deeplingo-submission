import { describe, expect, it } from "vitest";
import { parseLibraryVideoSummary, parseLibraryVideoDetail } from "./libraryModels";
import { ApiError } from "../../lib/api/errors";

const UUID = "0b9c4c85-6f3e-4a63-9f8f-3b1d2a4c5d6e";
const UUID2 = "11111111-2222-3333-4444-555555555555";

const validSummary = {
  library_item_id: UUID,
  video_id: UUID2,
  title: "Me at the zoo",
  thumbnail_url: null,
  duration_ms: 19000,
  source: "youtube",
  processing_status: "ready",
  learning_status: "ready",
  learning_object_count: 10,
  learning_prepared_language_code: "vi",
  language_code: "en",
  added_at: "2026-09-24T10:00:00Z",
  failure: null,
};

describe("library DTO parsing", () => {
  it("parses a valid summary", () => {
    const parsed = parseLibraryVideoSummary(validSummary);
    expect(parsed.title).toBe("Me at the zoo");
    expect(parsed.processing_status).toBe("ready");
    expect(parsed.failure).toBeNull();
  });

  it("rejects unknown processing status (never becomes ready)", () => {
    expect(() =>
      parseLibraryVideoSummary({ ...validSummary, processing_status: "transcript_ready" }),
    ).toThrow(ApiError);
  });

  it("rejects an omitted service-emitted learning_status", () => {
    const { learning_status, ...without } = validSummary;
    expect(learning_status).toBe("ready");
    expect(() => parseLibraryVideoSummary(without)).toThrow(ApiError);
  });

  it("parses retryable failure", () => {
    const parsed = parseLibraryVideoSummary({
      ...validSummary,
      processing_status: "failed",
      failure: { code: "transcript_unavailable", retryable: false, message: "no captions" },
    });
    expect(parsed.failure?.code).toBe("transcript_unavailable");
    expect(parsed.failure?.retryable).toBe(false);
  });

  it("rejects malformed failure codes", () => {
    expect(() => parseLibraryVideoSummary({
      ...validSummary,
      failure: { code: "mystery_code", retryable: true, message: "?" },
    })).toThrow(ApiError);
  });

  it("requires transcript_available on detail", () => {
    expect(() => parseLibraryVideoDetail(validSummary)).toThrow(ApiError);
    const detail = parseLibraryVideoDetail({ ...validSummary, transcript_available: true, description: null });
    expect(detail.transcript_available).toBe(true);
  });

  it("rejects non-uuid identity", () => {
    expect(() => parseLibraryVideoSummary({ ...validSummary, library_item_id: "nope" })).toThrow(ApiError);
  });

  it("rejects arrays and nulls", () => {
    expect(() => parseLibraryVideoSummary(null)).toThrow(ApiError);
    expect(() => parseLibraryVideoSummary([])).toThrow(ApiError);
  });
});
