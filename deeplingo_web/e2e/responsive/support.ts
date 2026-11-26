import { expect, type Page, type Route } from "@playwright/test";

// Fixtures for the responsive screenshot suite. This is a copy of the deterministic gate's backend mock
// (e2e/deterministic/app.spec.ts): every API request is answered locally and every external host is aborted,
// so the suite needs no backend, no Supabase, no YouTube and no AI provider.

export const API = "/api/v1/v3";
export const JWT = "e2e-dummy-jwt.header.token";

export const LIB_ID = "11111111-1111-1111-1111-111111111111";
export const LIB_ID_FAILED = "99999999-9999-9999-9999-999999999999";
export const VID_ID = "22222222-2222-2222-2222-222222222222";
export const SEG_ID = "33333333-4444-5555-6666-777777777777";
export const LO_ID = "55555555-6666-7777-8888-999999999999";
export const QUESTION_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa";
export const CONCEPT_ID = "53a24597-033f-461e-95f7-4c8e8ad02ed5";

const readyVideo = {
  library_item_id: LIB_ID,
  video_id: VID_ID,
  title: "Me at the zoo",
  thumbnail_url: null,
  duration_ms: 19000,
  source: "youtube",
  processing_status: "ready",
  learning_status: "ready",
  learning_object_count: 4,
  learning_prepared_language_code: "vi",
  language_code: "en",
  added_at: "2026-09-24T10:00:00Z",
  failure: null,
};

const failedVideo = {
  ...readyVideo,
  library_item_id: LIB_ID_FAILED,
  title: "Broken upload",
  processing_status: "failed",
  learning_status: "not_started",
  failure: { code: "video_unavailable", retryable: false, message: "" },
};

const transcript = {
  library_item_id: LIB_ID,
  language_code: "en",
  translation_language_code: "vi",
  segments: [
    {
      segment_id: SEG_ID,
      sequence: 1,
      text: "Elephants can live to seventy years old, or even longer.",
      start_ms: 1200,
      end_ms: 7974,
      translation: { language_code: "vi", text: "Voi có thể sống tới bảy mươi tuổi." },
      romanizations: [],
      learning_objects: [
        { learning_object_id: LO_ID, start_codepoint: 0, end_codepoint: 9 },
      ],
    },
    {
      segment_id: "44444444-5555-6666-7777-888888888888",
      sequence: 2,
      text: "All right, so here we are in front of the elephants.",
      start_ms: 7974,
      end_ms: 18881,
      translation: null,
      romanizations: [],
      learning_objects: [],
    },
  ],
};

export function json(route: Route, body: unknown, status = 200): void {
  void route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

// The live harness opens the study part the server cut, as a learner does.
async function mockStudyParts(page: Page) {
  await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/parts", (route) => json(route, {
    transcript_id: SEG_ID, source: "ai",
    parts: [{ start_segment_id: SEG_ID, end_segment_id: SEG_ID, start_ms: 1200, end_ms: 7974, segment_count: 1, title: "One" }],
  }));
}

export async function mockBackend(page: Page): Promise<string[]> {
  const seen: string[] = [];
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith(`${API}/`)) {
      seen.push(`${route.request().method()} ${url.pathname}${url.search}`);
      const auth = route.request().headers()["authorization"];
      expect.soft(auth, "learner APIs must receive the seeded bearer JWT").toBe(`Bearer ${JWT}`);
      if (url.pathname === `${API}/learner/me/agent/consent` && route.request().method() === "GET") {
        return json(route, { status: "granted", decided_at: "2026-10-29T10:00:00Z" });
      }
      if (url.pathname === `${API}/learner/me/agent/memory` && route.request().method() === "GET") return json(route, { items: [] });
      if (url.pathname === `${API}/learner/me/language-profile`) {
        return json(route, { learning_language: "en", support_language: "vi", is_complete: true });
      }
      if (url.pathname === `${API}/learner/me/lists` && route.request().method() === "GET") return json(route, []);
      if (url.pathname === `${API}/learner/me/word-sets`) return json(route, []);
      // One saved word, so All words can open its Review sheet.
      if (url.pathname === `${API}/learner/me/words` && route.request().method() === "GET") {
        return json(route, { summary: null, words: [{ concept_id: CONCEPT_ID, language_code: "en", text: "elephant", kind: "word", gloss: "con voi",
          list: "saved", saved: true, explicit: true, save_source: "manual", status: "active", rung: 0, next_review_at: null }] });
      }
      // FR-4.2: Home is led by the agent: the server's plan holds the suggestions.
      if (url.pathname === `${API}/learner/me/plan` && route.request().method() === "GET") {
        return json(route, { plan_id: "cccccccc-0000-4000-8000-000000000001", day: url.searchParams.get("day"),
          language_code: "en", intro: "Chào bạn! Hôm nay mình có vài gợi ý nhỏ.", items: [
            { id: "cccccccc-0000-4000-8000-000000000002", kind: "review", status: "open", minutes: 2, item_count: 3,
              library_item_id: null, video_title: null, companion_entry: null, reason: "3 mục đã đến lúc ôn." },
            { id: "cccccccc-0000-4000-8000-000000000003", kind: "video_practice", status: "open", minutes: 5,
              item_count: null, library_item_id: LIB_ID, video_title: "Me at the zoo", companion_entry: null,
              reason: "Tiếp tục xem video “Me at the zoo” từ chỗ bạn đã dừng." },
            { id: "cccccccc-0000-4000-8000-000000000004", kind: "conversation", status: "open", minutes: 5,
              item_count: null, library_item_id: null, video_title: null, companion_entry: "home",
              reason: "Chọn một chủ đề rồi nói chuyện với mình." },
          ] });
      }
      if (url.pathname.startsWith(`${API}/learner/me/plan/items/`) && route.request().method() === "POST") {
        return json(route, { id: url.pathname.split("/").at(-2), kind: "review", status: "accepted", minutes: 2,
          item_count: 3, library_item_id: null, video_title: null, companion_entry: null, reason: "x" });
      }
      // M2.2: the server picks what Home resumes; Watch then reads the same saved place.
      if (url.pathname === `${API}/learner/me/continue-learning`) {
        return json(route, { item: { library_item_id: LIB_ID, title: "Me at the zoo", thumbnail_url: null,
          duration_ms: 19000, position_ms: 8000, region: null, updated_at: "2026-10-20T10:00:00Z" } });
      }
      if (url.pathname === `${API}/learner/me/library/videos` && route.request().method() === "GET") {
        return json(route, [readyVideo, failedVideo]);
      }
      if (url.pathname === `${API}/learner/me/progress`) {
        const heatmap = Array.from({ length: 84 }, (_, i) => ({
          date: new Date(Date.UTC(2026, 9, 14) - (83 - i) * 86400000).toISOString().slice(0, 10),
          count: i >= 81 ? 2 : i % 4 === 0 ? 1 : 0,
        })).filter((d) => d.count > 0);
        return json(route, {
          language: null, languages: ["en"], utc_offset_minutes: 0, window_days: 365,
          streak: { current: 3, longest: 3, active_days: heatmap.length }, heatmap,
          cards: [], accuracy: [], pronunciation: [], weak_words: [], grammar: { learned: 0, done_correctly: 0 },
          regions_completed: 0, speaking: { sessions: 0, minutes: 0, weeks: [] },
        });
      }
      if (url.pathname === `${API}/learner/me/library/videos/${LIB_ID}`) {
        return json(route, { ...readyVideo, description: null, transcript_available: true });
      }
      if (url.pathname === `${API}/learner/me/library/videos/${LIB_ID}/playback`) {
        return json(route, {
          library_item_id: LIB_ID,
          video_id: VID_ID,
          provider: "youtube",
          external_video_id: "jNQXAC9IVRw",
          title: "Me at the zoo",
          language_code: "en",
          duration_ms: 19000,
        });
      }
      if (url.pathname === `${API}/learner/me/library/videos/${LIB_ID}/transcript`) {
        return json(route, transcript);
      }
      if (url.pathname.startsWith(`${API}/learner/me/library/videos/${LIB_ID}/workspace`)) {
        return json(route, { library_item_id: LIB_ID, position_ms: null, region: null, updated_at: null });
      }
      // M1 S6: the question arrives without its answer; the check comes from the server.
      if (url.pathname === `${API}/learner/me/library/videos/${LIB_ID}/region-questions`) {
        return json(route, { status: "ready", questions: [{ id: QUESTION_ID, position: 1,
          question: "Voi có thể sống bao lâu?", options: ["Khoảng 7 năm", "Khoảng 70 năm", "Khoảng 17 năm", "Khoảng 700 năm"] }] });
      }
      if (url.pathname === `${API}/learner/me/library/videos/${LIB_ID}/region-questions/${QUESTION_ID}/answer`) {
        const body = route.request().postDataJSON() as { id: string; selected_option: number };
        if (Object.keys(body).sort().join() !== "id,selected_option") return json(route, { detail: { code: "invalid" } }, 422);
        return json(route, { id: body.id, question_id: QUESTION_ID, status: "created", selected_option: body.selected_option,
          correct: body.selected_option === 1, correct_index: 1, evidence_segment_id: SEG_ID,
          evidence_quote: "live to seventy years old", explanation: "Câu đầu nói voi sống tới bảy mươi tuổi." });
      }
      if (url.pathname.endsWith("/concept")) {
        return json(route, {
          library_item_id: LIB_ID,
          learning_object_id: LO_ID,
          expression: "Elephants",
          occurrence_text: "Elephants",
          source_segment_text: transcript.segments[0].text,
          start_codepoint: 0,
          end_codepoint: 9,
          learning_language_code: "en",
          support_language_code: "vi",
          contextual_meaning: "con voi",
          explanation: null,
        });
      }
      return json(route, { detail: { code: "not_mocked", message: `unmocked ${url.pathname}` } }, 404);
    }
    if (url.origin === "http://localhost:5173") {
      return route.continue();
    }
    // Prove determinism: nothing outside the dev server is ever contacted.
    return route.abort();
  });
  return seen;
}

// Seeds a Supabase v2 session into localStorage before app scripts run.
export async function seedSession(page: Page): Promise<void> {
  const session = {
    access_token: JWT,
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "dummy-refresh-token",
    user: {
      id: "e2e-user-0001",
      aud: "authenticated",
      role: "authenticated",
      email: "e2e@ci.invalid",
      app_metadata: {},
      user_metadata: {},
      created_at: "2026-01-01T00:00:00Z",
    },
  };
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key, value as string);
    },
    ["sb-ci-dummy-auth-token", JSON.stringify(session)],
  );
}
