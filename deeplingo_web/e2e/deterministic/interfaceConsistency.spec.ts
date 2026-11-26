import { expect, test, type Page } from "@playwright/test";
import { progressBody } from "./progressFixture";

const API = "/api/v1/v3/learner/me";
const VIDEO = "11111111-1111-4111-8111-111111111111";
const SEGMENT = "22222222-2222-4222-8222-222222222222";
const WORD = "33333333-3333-4333-8333-333333333333";

async function fixture(page: Page) {
  await page.addInitScript(() => localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
    access_token: "e2e-dummy.header.token", token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: "e2e-user", aud: "authenticated", role: "authenticated",
      email: "preview@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
  })));
  const writes: { path: string; body: unknown }[] = [];
  const unexpected: string[] = [];
  await page.route("**/*", route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (path.startsWith("/api/")) {
      if (route.request().method() !== "GET" && !path.endsWith("/translations")) writes.push({ path, body: route.request().postDataJSON() });
      if (path === `${API}/language-profile`) return json({ learning_language: "en", support_language: "vi", declared_level: null, is_complete: true });
      if (path === `${API}/words`) return json({ words: [{ concept_id: WORD, language_code: "en", text: "reservation", gloss: "a booking", kind: "word",
        saved: true, explicit: true, list: "saved", status: "active", rung: 0, save_source: "manual", next_review_at: null }], summary: null });
      if (path === `${API}/lists` || path === `${API}/library/videos` || path === `${API}/word-sets`) return json([]);
      if (path === `${API}/speaking-sessions`) return json({ sessions: [], next_cursor: null });
      if (path === `${API}/progress`) return json(progressBody());
      if (path === `${API}/agent/consent`) return json({ status: "granted", decided_at: "2026-10-31T01:00:00Z" });
      if (path === `${API}/agent/transcripts/consent`) return json({ status: "revoked", decided_at: "2026-11-07T01:00:00Z", active: false });
      if (path === `${API}/agent/transcripts`) return json({ transcripts: [], next_before: null });
      if (path === `${API}/agent/memory`) return json({ items: [] });
      if (path === `${API}/review/decks`) return json({ decks: [] });
      if (path === `${API}/grammar/en`) return json({ language_code: "en", support_language: "vi", levels: ["A1"], level: "A1",
        topics: [{ key: "be", title: "To be" }], points: [{ key: "be.present", title: "Present tense", topic_key: "be", lesson: null, exercise_count: 2,
          attempts: 1, correct_count: 1, incorrect_count: 0, lesson_learned_at: null, last_correct_at: null }], redo: [] });
      if (path.endsWith("/examples")) return json({ examples: [] });
      // Subtitle translations are shared content, not learner state; the study region spec covers them.
      if (path === `${API}/library/videos/${VIDEO}/translations`) return json({ status: "not_needed", language_code: null, translated: 0 });
      if (path === `${API}/library/videos/${VIDEO}/playback`) return json({ library_item_id: VIDEO, video_id: VIDEO, provider: "youtube", external_video_id: "jNQXAC9IVRw", title: "Video title", language_code: "en", duration_ms: 30000 });
      if (path === `${API}/library/videos/${VIDEO}/transcript`) return json({ library_item_id: VIDEO, language_code: "en", translation_language_code: "vi", segments: [{
        segment_id: SEGMENT, sequence: 1, text: "I need a reservation.", start_ms: 0, end_ms: 5000, translation: null, romanizations: [], learning_objects: [],
      }] });
      // AI study parts are covered by aiStudyParts.spec; here they are unavailable so the screen stays read-only.
      if (path === `${API}/library/videos/${VIDEO}/parts`) return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
      if (path === `${API}/library/videos/${VIDEO}/workspace`) return json({ library_item_id: VIDEO, position_ms: null, region: null, updated_at: null });
      if (path.endsWith("/region-questions")) return json({ status: "no_region", questions: [] });
      if (path.endsWith("/grammar-explanations")) return json({ segment_id: SEGMENT, scope: "sentence", source_text: "I need a reservation.", support_language_code: "vi", source: "ai_unverified", explanation: {
        sentence_structure: { title: "Structure", text: "Subject and verb." }, grammar: { title: "Grammar", text: "Present simple." }, important_words: { title: "Words", text: "reservation" },
      } });
      unexpected.push(path); return route.abort();
    }
    return url.origin === "http://localhost:5173" ? route.continue() : route.abort();
  });
  return { writes, unexpected };
}

for (const width of [390, 1180, 1440]) for (const theme of ["light", "dark"] as const) {
  test(`consistent video tools, account and learning screens ${width}px ${theme}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    const { writes, unexpected } = await fixture(page);
    await page.goto(`/library/videos/${VIDEO}/watch`);
    const transcript = page.getByRole("region", { name: "Transcript" });
    await expect(transcript).toBeVisible();
    await expect(page.getByRole("link", { name: "Back home" })).toContainText("");
    expect(writes).toEqual([]);
    const player = page.locator(".player-frame");
    for (const tab of ["Dictation", "Shadowing", "Questions"]) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      await expect(transcript).toBeHidden();
      const panel = page.getByRole("tabpanel");
      await expect(panel).toBeVisible();
      if (width >= 700) {
        const left = await player.boundingBox(), right = await panel.boundingBox();
        expect(right!.x).toBeGreaterThanOrEqual(left!.x + left!.width);
      }
      await page.screenshot({ path: info.outputPath(`video-${tab}.png`), fullPage: true });
    }
    await page.getByRole("tab", { name: "Transcript", exact: true }).click();
    await transcript.getByRole("button", { name: "Analyse sentence" }).click();
    await expect(page.getByRole("dialog", { name: "Grammar explanation" })).toBeVisible();
    expect(writes).toEqual([{ path: `${API}/library/videos/${VIDEO}/grammar-explanations`, body: {
      segment_id: SEGMENT, start_codepoint: 0, end_codepoint: 21, scope: "sentence",
    } }]);
    await page.getByRole("button", { name: "Close grammar explanation" }).click();
    await page.getByRole("button", { name: "Account menu" }).click();
    const menu = page.getByRole("menu", { name: "Account menu" });
    await expect(menu.getByRole("menuitem")).toHaveCount(3);
    await expect(menu.getByRole("menuitem", { name: "Settings" })).toHaveAttribute("href", "/account#learning-preferences");
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Account menu" })).toBeFocused();
    const dock = await page.locator(".agent-launcher").boundingBox();
    if (width >= 700) expect(dock!.x + dock!.width).toBeGreaterThanOrEqual(width - 32);
    else expect(dock!.x + dock!.width).toBeLessThanOrEqual(width);
    if (width >= 700) expect((await page.locator(".topbar").boundingBox())!.width).toBeLessThanOrEqual(960);
    await page.goto("/words?level=0");
    await expect(page.getByText("reservation", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Set your level in Profile" })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath("words.png"), fullPage: true });
    await page.goto("/words/lists");
    await expect(page.getByRole("button", { name: "Agent suggests word groups" })).toHaveCount(0);
    await page.getByRole("button", { name: "Open agent" }).click();
    // Tata no longer groups saved words into notebooks; the learner makes notebooks.
    await expect(page.getByRole("dialog", { name: "Agent conversation" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Organise saved words" })).toHaveCount(0);
    expect(writes).toHaveLength(1);
    await page.getByRole("button", { name: "Close agent" }).click();
    // The old grammar page now opens the notebook's Grammar tab.
    await page.goto("/review/quick?mode=grammar");
    await expect(page).toHaveURL(/\/words\/lists\?tab=grammar$/);
    await expect(page.getByRole("button", { name: "Practise now" })).toBeVisible();
    await expect(page.getByText("Right and wrong answers are saved separately for each grammar point.")).toHaveCount(0);
    await page.screenshot({ path: info.outputPath("grammar-review.png"), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(unexpected).toEqual([]);
  });
}
