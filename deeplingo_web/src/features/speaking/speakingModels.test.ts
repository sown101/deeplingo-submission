import { describe, expect, it } from "vitest";
import { parseShadowingAssessment } from "./speakingModels";
import { shadowingPayload } from "../../test/speakingFixtures";

const SEGMENT = "11111111-2222-3333-4444-555555555555";

describe("speaking decoders", () => {
  it("decodes a shadowing assessment for the requested segment only", () => {
    const parsed = parseShadowingAssessment(shadowingPayload, SEGMENT);
    expect(parsed.band).toBe("good");
    expect(parsed.words[1].error_type).toBe("mispronunciation");
    expect(() => parseShadowingAssessment(shadowingPayload, "99999999-2222-3333-4444-555555555555")).toThrow();
  });

  it("rejects out-of-range scores and unknown enums", () => {
    expect(() => parseShadowingAssessment({ ...shadowingPayload, scores: { ...shadowingPayload.scores, accuracy: 140 } }, SEGMENT)).toThrow();
    expect(() => parseShadowingAssessment({ ...shadowingPayload, band: "perfect" }, SEGMENT)).toThrow();
    expect(() =>
      parseShadowingAssessment({ ...shadowingPayload, words: [{ ...shadowingPayload.words[0], error_type: "rude" }] }, SEGMENT),
    ).toThrow();
  });
});

describe("voice consent (Codex review 2026-11-05)", () => {
  it("tells the learner where to allow voice processing", async () => {
    const { speakingErrorMessage } = await import("./SpeakingFeedback");
    const { ApiError } = await import("../../lib/api/errors");
    expect(speakingErrorMessage(new ApiError("conflict", 409, { code: "voice_consent_required" })))
      .toBe("Allow voice processing in Profile to practise speaking.");
  });
});
