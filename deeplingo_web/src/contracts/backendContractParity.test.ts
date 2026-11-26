import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/api/apiClient";
import { ApiError, isRetryable } from "../lib/api/errors";
import type { AuthGateway } from "../lib/auth/authGateway";
import { parseLanguages, parseLanguageProfile, parseLearnerInitializationResponse } from "../features/onboarding/onboardingApi";
import { parseLibraryVideoSummary, parseLibraryVideoDetail } from "../features/library/libraryModels";
import { parseImportResponse } from "../features/library/libraryApi";
import { parsePlayableVideo, parseVideoTranscriptView, parseConceptInteractionView } from "../features/video/videoModels";
import { parseVideoWorkspace } from "../features/video/workspace/workspaceModels";
import {
  apiErrorBodies,
  conceptInteraction,
  conceptInteractionFromDictionary,
  ids,
  languageProfile,
  languages,
  learnerInitialization,
  libraryDetails,
  libraryDetail,
  libraryImport,
  librarySummary,
  playback,
  transcript,
  uninitializedLanguageProfile,
  workspace,
} from "./backendV1Fixtures";

describe("current backend contract fixtures at Web decoder boundaries", () => {
  it("decodes language catalog and initialization responses without turning malformed success into defaults", () => {
    expect(parseLanguages(languages)).toHaveLength(2);
    expect(parseLanguages([{ ...languages[0], authority_note: { user_id: "not-authority" } }])[0]).not.toHaveProperty("authority_note");
    expect(() => parseLanguages([{ ...languages[0], display_order: "1" }])).toThrow(ApiError);
    expect(() => parseLanguages([{ ...languages[0], name_en: undefined }])).toThrow(ApiError);

    expect(parseLanguageProfile(languageProfile).is_complete).toBe(true);
    expect(parseLanguageProfile(uninitializedLanguageProfile)).toEqual(uninitializedLanguageProfile);
    expect(() => parseLanguageProfile({ ...languageProfile, is_complete: undefined })).toThrow(ApiError);
    expect(() => parseLanguageProfile({ ...uninitializedLanguageProfile, learning_language: undefined })).toThrow(ApiError);
    expect(() => parseLanguages([{ ...languages[0], is_active: undefined }])).toThrow(ApiError);

    expect(parseLearnerInitializationResponse(learnerInitialization)).toBeUndefined();
    expect(() => parseLearnerInitializationResponse({ ...learnerInitialization, profile_status: "unknown" })).toThrow(ApiError);
    expect(() => parseLearnerInitializationResponse({ ...learnerInitialization, profile_status: "future" })).toThrow(ApiError);
  });

  it("parses every current Library status and nullable detail while rejecting drift", () => {
    for (const fixture of Object.values(libraryDetails)) {
      expect(parseLibraryVideoSummary(fixture).library_item_id).toBe(ids.libraryItem);
    }
    expect(parseLibraryVideoDetail(libraryDetail).description).toBeNull();
    expect(parseImportResponse(libraryImport).command_status).toBe("accepted");
    expect(() => parseImportResponse({ ...libraryImport, command_status: undefined })).toThrow(ApiError);
    expect(() => parseImportResponse({ ...libraryImport, item: undefined })).toThrow(ApiError);
    expect(parseLibraryVideoSummary({ ...librarySummary, user_id: "not-authority", mastery: 1 })).not.toHaveProperty("user_id");

    for (const key of ["learning_status", "learning_object_count", "thumbnail_url", "duration_ms", "failure"] as const) {
      const malformed = { ...librarySummary } as Record<string, unknown>;
      delete malformed[key];
      expect(() => parseLibraryVideoSummary(malformed)).toThrow(ApiError);
    }
    expect(() => parseLibraryVideoSummary({ ...librarySummary, learning_status: "future_status" })).toThrow(ApiError);
    expect(() => parseLibraryVideoSummary({ ...librarySummary, learning_object_count: -1 })).toThrow(ApiError);
    expect(() => parseLibraryVideoSummary({ ...librarySummary, duration_ms: undefined })).toThrow(ApiError);
    expect(() => parseLibraryVideoSummary({ ...librarySummary, failure: { code: "unknown", retryable: true, message: "x" } })).toThrow(ApiError);
    expect(() => parseLibraryVideoSummary({ ...libraryDetails.processingFailed, failure: null })).toThrow(ApiError);
    expect(() => parseLibraryVideoDetail({ ...libraryDetail, description: undefined })).toThrow(ApiError);
  });

  it("parses the workspace fixture, an empty workspace and rejects another Library item", () => {
    expect(parseVideoWorkspace(workspace, ids.libraryItem)).toEqual({
      library_item_id: ids.libraryItem, position_ms: 520000, region: workspace.region,
    });
    expect(parseVideoWorkspace({ ...workspace, position_ms: null, region: null, updated_at: null }, ids.libraryItem).region).toBeNull();
    expect(() => parseVideoWorkspace(workspace, ids.video)).toThrow(ApiError);
  });

  it("parses playback, transcript and Concept fixtures and rejects malformed success items", () => {
    expect(parsePlayableVideo(playback).external_video_id).toBe("jNQXAC9IVRw");
    expect(parsePlayableVideo({ ...playback, duration_ms: null }).duration_ms).toBeNull();
    expect(() => parsePlayableVideo({ ...playback, duration_ms: -1 })).toThrow(ApiError);

    expect(parseVideoTranscriptView(transcript).segments).toHaveLength(1);
    expect(parseVideoTranscriptView({ ...transcript, segments: [{ ...transcript.segments[0], translation: null }] }).segments[0].translation).toBeNull();
    expect(() => parseVideoTranscriptView({ ...transcript, translation_language_code: undefined })).toThrow(ApiError);
    expect(() => parseVideoTranscriptView({ ...transcript, segments: [{ ...transcript.segments[0], end_ms: 0 }] })).toThrow(ApiError);
    expect(() => parseVideoTranscriptView({ ...transcript, segments: [{ ...transcript.segments[0], learning_objects: [{ learning_object_id: ids.learningObject, start_codepoint: 0, end_codepoint: 999 }] }] })).toThrow(ApiError);
    expect(parseVideoTranscriptView({ ...transcript, forbidden_review_state: { fsrs: "ignored" } })).not.toHaveProperty("forbidden_review_state");

    expect(parseConceptInteractionView(conceptInteraction).explanation).toBeNull();
    expect(() => parseConceptInteractionView({ ...conceptInteraction, explanation: undefined })).toThrow(ApiError);
    expect(() => parseConceptInteractionView({ ...conceptInteraction, expression: undefined })).toThrow(ApiError);
    expect(() => parseConceptInteractionView({ ...conceptInteraction, explanation: "   " })).toThrow(ApiError);
    expect(() => parseConceptInteractionView({ ...conceptInteraction, end_codepoint: 500 })).toThrow(ApiError);
    expect(parseConceptInteractionView({ ...conceptInteraction, expected_answer: "ignored" })).not.toHaveProperty("expected_answer");

    expect(parseConceptInteractionView(conceptInteraction).meaning_provenance).toBe("unverified");
    const fromDictionary = parseConceptInteractionView(conceptInteractionFromDictionary);
    expect(fromDictionary.meaning_provenance).toBe("dictionary");
    expect(fromDictionary.dictionary_sense).toEqual(conceptInteractionFromDictionary.dictionary_sense);
    // An older backend that omits both fields serves unverified meanings.
    const { meaning_provenance: _p, dictionary_sense: _d, ...older } = conceptInteraction;
    expect(parseConceptInteractionView(older)).toMatchObject({ meaning_provenance: "unverified", dictionary_sense: null });
    const sense = conceptInteractionFromDictionary.dictionary_sense;
    for (const broken of [
      { ...conceptInteraction, meaning_provenance: "dictionary" },
      { ...conceptInteraction, dictionary_sense: sense },
      { ...conceptInteraction, meaning_provenance: "verified_by_ai" },
      { ...conceptInteractionFromDictionary, dictionary_sense: { ...sense, source_url: "javascript:alert(1)" } },
      { ...conceptInteractionFromDictionary, dictionary_sense: { ...sense, license_url: "http://example.test/" } },
      { ...conceptInteractionFromDictionary, dictionary_sense: { ...sense, definition: "" } },
    ]) {
      expect(() => parseConceptInteractionView(broken)).toThrow(ApiError);
    }
  });

});

describe("learner-safe API error compatibility fixtures", () => {
  it("keeps status/code/retryability distinct and never presents server details as learner copy", () => {
    const cases = [
      [401, apiErrorBodies.unauthorized401, "unauthorized", false],
      [400, apiErrorBodies.validation400, "validation", false],
      [404, apiErrorBodies.notFound404, "not_found", false],
      [409, apiErrorBodies.submissionConflict409, "conflict", false],
      [422, apiErrorBodies.validation422, "validation", false],
      [503, apiErrorBodies.attemptUnavailable503, "server", true],
      [503, apiErrorBodies.practiceUnavailable503, "server", true],
      [500, apiErrorBodies.internal500, "server", true],
    ] as const;
    for (const [status, body, kind, retryable] of cases) {
      const responseBody = body.detail;
      const error = new ApiError(
        status === 401 ? "unauthorized" : status === 404 ? "not_found" : status === 409 ? "conflict" : status === 400 || status === 422 ? "validation" : "server",
        status,
        typeof responseBody === "string"
          ? { message: responseBody, raw: body }
          : { code: responseBody.code, message: responseBody.message, raw: body },
      );
      expect(error.kind).toBe(kind);
      expect(isRetryable(error)).toBe(retryable);
      expect(error.message).not.toContain(typeof responseBody === "string" ? responseBody : responseBody.message ?? "");
    }
    const conflict = new ApiError("conflict", 409, { message: "submission_conflict", raw: apiErrorBodies.submissionConflict409 });
    expect(conflict.detail.message).toBe("submission_conflict");
    expect(conflict.message).not.toContain("private internal diagnostic");
    const server = new ApiError("server", 500, { message: "private internal diagnostic — must not be rendered", raw: apiErrorBodies.internal500 });
    expect(server.detail.raw).toEqual(apiErrorBodies.internal500);
    expect(server.message).toBe("The service is temporarily unavailable.");
    // Feature screens render fixed scope-specific copy; transport diagnostics
    // are retained for classification only and are never the UI state here.
    const learnerCopy = "Practice could not start. Please retry.";
    expect(learnerCopy).not.toContain(server.detail.message ?? "");
  });

  it("keeps network, timeout, malformed success and HTTP server errors distinct", async () => {
    const gateway: AuthGateway = {
      getClient: () => { throw new Error("unused"); },
      currentSession: vi.fn(async () => ({ userId: "user", accessToken: "token" })),
      onAuthStateChange: () => () => {},
      signUp: async () => ({ needsConfirmation: false }),
      signIn: async () => {},
      signOut: async () => {},
      resetPassword: async () => {},
      updatePassword: async () => {},
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response("not-json", { status: 200 })));
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: gateway });
    await expect(client.get("/learner/me/words")).rejects.toMatchObject({ kind: "parse", status: 200 });
    vi.unstubAllGlobals();

    const httpCases = [
      [401, apiErrorBodies.unauthorized401, "unauthorized", false],
      [400, apiErrorBodies.validation400, "validation", false],
      [404, apiErrorBodies.notFound404, "not_found", false],
      [409, apiErrorBodies.submissionConflict409, "conflict", false],
      [422, apiErrorBodies.validation422, "validation", false],
      [503, apiErrorBodies.attemptUnavailable503, "server", true],
      [503, apiErrorBodies.practiceUnavailable503, "server", true],
      [500, apiErrorBodies.internal500, "server", true],
    ] as const;
    for (const [status, body, kind, retryable] of httpCases) {
      vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
      let caught: unknown;
      try {
        await client.get("/learner/me/words");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(ApiError);
      const error = caught as ApiError;
      expect(error.kind).toBe(kind);
      expect(isRetryable(error)).toBe(retryable);
      expect(error.message).not.toContain("private internal diagnostic");
      if (status === 409) expect(error.detail.message).toBe("submission_conflict");
      vi.unstubAllGlobals();
    }

    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    await expect(client.get("/learner/me/words")).rejects.toMatchObject({ kind: "network", status: null });
    vi.unstubAllGlobals();

    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    await expect(client.get("/learner/me/words", { timeoutMs: 1 })).rejects.toMatchObject({ kind: "timeout", status: null });
    vi.unstubAllGlobals();
  });
});
