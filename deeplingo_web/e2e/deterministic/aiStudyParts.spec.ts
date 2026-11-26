import { expect, test } from "@playwright/test";

// 2026-11-05: opening a video sets the study region to the AI part holding the saved position.
// All server responses are synthetic; no live AI.
const API = "/api/v1/v3/learner/me";
const ITEM = "11111111-1111-4111-8111-111111111111";
const TRACK = "22222222-2222-4222-8222-222222222222";
const seg = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const segments = Array.from({ length: 12 }, (_, i) => ({
  segment_id: seg(i + 1), sequence: i + 1, text: `Sentence ${i + 1}.`, start_ms: i * 5000, end_ms: (i + 1) * 5000,
  translation: null, romanizations: [], learning_objects: [],
}));
const part = (from: number, to: number, title: string) => ({
  start_segment_id: seg(from), end_segment_id: seg(to), start_ms: (from - 1) * 5000, end_ms: to * 5000,
  segment_count: to - from + 1, title,
});

test("opening a video starts on the AI part holding the saved position", async ({ page }, info) => {
  await page.addInitScript(() => {
    localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({ access_token: "parts.dummy.jwt", token_type: "bearer",
      refresh_token: "dummy-refresh", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: "parts-ci-user", aud: "authenticated", role: "authenticated", email: "parts@ci.invalid",
        app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" } }));
  });
  const regions: unknown[] = [];
  let region: unknown = null;
  const unexpected: string[] = [];
  await page.route("**/*", route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (!path.startsWith("/api/")) return new URL(request.url()).origin === "http://localhost:5173" ? route.continue() : route.abort();
    if (path === `${API}/language-profile`) return json({ learning_language: "en", support_language: "vi", is_complete: true });
    if (path === `${API}/agent/consent`) return json({ status: "granted", decided_at: "2026-10-29T10:00:00Z" });
    if (path.endsWith("/playback")) return json({ library_item_id: ITEM, video_id: ITEM, provider: "youtube",
      external_video_id: "jNQXAC9IVRw", title: "Parts video", language_code: "en", duration_ms: 60000 });
    if (path.endsWith("/transcript")) return json({ library_item_id: ITEM, language_code: "en", translation_language_code: null, segments });
    if (path.endsWith("/parts")) return json({ transcript_id: TRACK, source: "ai",
      parts: [part(1, 4, "Chào hỏi"), part(5, 8, "Gọi món"), part(9, 12, "Thanh toán")] });
    if (path.endsWith("/workspace/region") && request.method() === "PUT") {
      const body = request.postDataJSON() as { start_segment_id: string; end_segment_id: string };
      regions.push(body);
      region = { transcript_id: TRACK, ...body, start_ms: 20000, end_ms: 40000, segment_count: 4, preparation: null };
      return json({ library_item_id: ITEM, position_ms: 25000, region });
    }
    if (path.endsWith("/workspace") || path.endsWith("/workspace/position")) return json({ library_item_id: ITEM, position_ms: 25000, region });
    if (path.endsWith("/region-questions")) return json({ status: "no_region", questions: [] });
    unexpected.push(`${request.method()} ${path}`);
    return route.abort();
  });
  await page.goto(`/library/videos/${ITEM}/watch`);
  await expect(page.getByText("Gọi món", { exact: true })).toBeVisible();
  expect(regions).toEqual([{ start_segment_id: seg(5), end_segment_id: seg(8) }]);
  await expect(page.getByRole("group", { name: "Change part" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("study-parts.png"), fullPage: true });
  expect(unexpected).toEqual([]);
});
