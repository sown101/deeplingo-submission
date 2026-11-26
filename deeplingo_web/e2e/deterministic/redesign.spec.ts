import { expect, test, type Page } from "@playwright/test";
import { progressBody } from "./progressFixture";
import { VI } from "../../src/i18n/vi";

const API = "/api/v1/v3/learner/me";
const VIDEO = "11111111-1111-4111-8111-111111111111";
const GROUP = "55555555-5555-4555-8555-555555555555";
const CONCEPT = "66666666-6666-4666-8666-666666666666";
const SEGMENT = "77777777-7777-4777-8777-777777777777";
const video = { library_item_id: VIDEO, video_id: VIDEO, title: "Du lịch Đà Nẵng", thumbnail_url: null,
  duration_ms: 360000, source: "youtube", processing_status: "ready", learning_status: "ready",
  learning_object_count: 3, learning_prepared_language_code: "vi", language_code: "en", added_at: "2026-10-31T01:00:00Z", failure: null };
const words = ["reservation", "itinerary", "check in"].map((text, index) => ({
  concept_id: index ? `${index}6666666-6666-4666-8666-666666666666` : CONCEPT, language_code: "en", text, gloss: ["đặt chỗ", "lịch trình", "làm thủ tục"][index], kind: "word",
  list: "saved", saved: true, save_source: "manual", explicit: true, status: "active", rung: [4, 3, 0][index], next_review_at: null,
}));
const groups = ["Du lịch", "Công việc", "Ăn uống", "Hằng ngày"].map((name, index) => ({ id: index ? `book-${index}` : GROUP, language_code: "en", name, description: null, word_count: 3, waiting_count: 0 }));

async function fixture(page: Page, signedIn: boolean) {
  await page.addInitScript(({ signedIn }) => {
    if (window.top !== window || window.location.origin !== "http://localhost:5173") return;
    localStorage.setItem("deeplingo.ui_language", "vi");
    if (signedIn) localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: "e2e-dummy-jwt.header.token", token_type: "bearer", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, refresh_token: "dummy-refresh-token",
      user: { id: "e2e-user-0001", aud: "authenticated", role: "authenticated", email: "e2e@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    }));
  }, { signedIn });
  const writes: string[] = [];
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.startsWith("/api/")) {
      if (route.request().method() !== "GET") writes.push(url.pathname);
      if (url.pathname === `${API}/language-profile`) return json({ learning_language: "en", support_language: "vi", declared_level: "B1", is_complete: true });
      if (url.pathname === "/api/v1/v3/languages") return json([
        { code: "en", name_en: "English", name_native: "English", script: "Latn", is_active: true, display_order: 1 },
        { code: "zh", name_en: "Chinese", name_native: "中文", script: "Hans", is_active: true, display_order: 2 },
        { code: "vi", name_en: "Vietnamese", name_native: "Tiếng Việt", script: "Latn", is_active: true, display_order: 3 },
      ]);
      if (url.pathname === `${API}/words`) return json({ words, summary: null });
      if (url.pathname === `${API}/review/decks`) return json({ decks: [{ language_code: "en", due_count: 2, new_count: 1, total_count: 3 }] });
      if (url.pathname === `${API}/review/en/due`) {
        const mode = url.searchParams.get("mode");
        const exercise = mode === "flashcard" ? { type: "flashcard", prompt: { text: "reservation", reading: null, meaning: "đặt chỗ", sentence: null } }
          : mode === "cloze" ? { type: "cloze", prompt: { sentence: "I would like to make a ____.", meaning: "đặt chỗ",
            source: { text: "I would like to make a ____.", origin: "video", library_item_id: VIDEO, start_ms: 0 } } }
          : { type: "choice", prompt: { text: "reservation", reading: null, sentence: "I would like to make a reservation.", options: ["đặt chỗ", "hành trình", "hành lý"] } };
        return json({ language_code: "en", due_count: 1, new_count: 0, cards: [{ concept_id: "c0000000-0000-4000-8000-000000000001", text: "reservation",
          reading: null, is_new: false, due_at: "2026-10-31T00:00:00Z", exercise }] });
      }
      if (url.pathname === `${API}/grammar/en`) return json({ language_code: "en", support_language: "vi", levels: ["A1"], level: "A1",
        topics: [{ key: "verbs", title: "Động từ" }], points: [{ key: "en.a1.be", title: "Động từ be", topic_key: "verbs", lesson: null,
          exercise_count: 4, attempts: 2, correct_count: 1, incorrect_count: 1, lesson_learned_at: null, last_correct_at: null }], redo: [] });
      if (url.pathname === `${API}/lists`) return json(groups);
      if (url.pathname === `${API}/lists/${GROUP}`) return json({ ...groups[0], words, waiting: [] });
      if (url.pathname.endsWith("/examples")) return json({ examples: [] });
      if (url.pathname === `${API}/library/videos`) return json([video]);
      if (url.pathname === `${API}/video-coverage`) return json([]);
      if (url.pathname === `${API}/speaking-sessions`) return json({ sessions: [], next_cursor: null });
      if (url.pathname === `${API}/progress`) return json(progressBody({ heatmap: [
        { date: "2026-10-26", count: 3 }, { date: "2026-10-31", count: 5 },
      ], pronunciation: [
        { date: "2026-10-20", score: 62, attempts: 1 }, { date: "2026-10-24", score: 71, attempts: 2 },
        { date: "2026-10-28", score: 68, attempts: 1 }, { date: "2026-10-31", score: 83, attempts: 1 },
      ] }));
      if (url.pathname === `${API}/companion/sessions`) return json({
        session_ticket: "synthetic.ticket", expires_at: "2026-11-01T01:00:00Z", turn: 0, max_turns: 20, finished: false,
        language_code: "en", support_language_code: "vi", entry: "home", library_item_id: null, topic: "Du lịch",
        learner_transcript: null, reply: "Where would you like to travel?", reply_support: "Bạn muốn đi du lịch ở đâu?",
        hints: { question: null, items: [], frame: null, model_sentence: null }, correction: null, used_items: [], next: "continue", audio: null, audio_status: "unavailable",
      });
      if (url.pathname === `${API}/agent/consent`) return json({ status: "granted", decided_at: "2026-10-31T01:00:00Z" });
      if (url.pathname === `${API}/agent/signals`) return json({ signals: [] });
      if (url.pathname === `${API}/library/videos/${VIDEO}/playback`) return json({ library_item_id: VIDEO, video_id: VIDEO, provider: "youtube", external_video_id: "jNQXAC9IVRw", title: video.title, language_code: "en", duration_ms: video.duration_ms });
      if (url.pathname === `${API}/library/videos/${VIDEO}/transcript`) return json({ library_item_id: VIDEO, language_code: "en", translation_language_code: "vi", segments: [
        { segment_id: SEGMENT, sequence: 1, text: "I would like to make a reservation.", start_ms: 0, end_ms: 5000, translation: { language_code: "vi", text: "Tôi muốn đặt chỗ." }, romanizations: [], learning_objects: [] },
      ] });
      if (url.pathname.startsWith(`${API}/library/videos/${VIDEO}/workspace`)) return json({ library_item_id: VIDEO, position_ms: null, region: null, updated_at: null });
      if (url.pathname === `${API}/library/videos/${VIDEO}`) return json({ ...video, description: null, transcript_available: true });
      return json({ detail: { code: "not_mocked" } }, 404);
    }
    if (url.origin === "http://localhost:5173") return route.continue();
    return route.abort();
  });
  return writes;
}

const screens = [
  { name: "landing", path: "/", heading: "Learn from real videos, then talk with Tata.", signedIn: false },
  { name: "signin", path: "/signin", heading: "Welcome back", signedIn: false },
  { name: "signup", path: "/signin?mode=signup", heading: "Create your account", signedIn: false },
  { name: "notebooks", path: "/words/lists", heading: "Notebooks", signedIn: true },
  { name: "notebook", path: `/words/lists/${GROUP}`, heading: "Du lịch", signedIn: true },
  { name: "words", path: "/words?level=0", heading: "Level: {name}", signedIn: true },
  { name: "review", path: "/review/en?types=choice", heading: "Review", signedIn: true },
  { name: "flashcards", path: `/notebook/${GROUP}/flashcards`, heading: "Flashcard", signedIn: true },
  { name: "writing", path: `/notebook/${GROUP}/writing`, heading: "Writing practice", signedIn: true },
  { name: "grammar", path: "/words/lists?tab=grammar", heading: "Notebooks", signedIn: true },
  { name: "progress", path: "/progress", heading: "Progress", signedIn: true },
  { name: "profile", path: "/account", heading: "Profile", signedIn: true },
  { name: "agent", path: "/agent", heading: "Agent", signedIn: true },
  { name: "voice", path: "/agent?mode=voice", heading: "Agent", signedIn: true },
  { name: "video", path: `/library/videos/${VIDEO}/watch`, heading: "Du lịch Đà Nẵng", signedIn: true },
];

for (const screen of screens) for (const width of [390, 1180, 1440, 2000]) for (const colorScheme of ["light", "dark"] as const) {
  test(`redesign ${screen.name} ${width}px ${colorScheme}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 960 });
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const writes = await fixture(page, screen.signedIn);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(screen.path);
    const heading = (VI[screen.heading] ?? screen.heading).replace("{name}", VI.Seen);
    await expect(page.getByRole("heading", { name: heading, level: 1 }).first()).toBeVisible();
    if (screen.name === "review") await expect(page.locator(".st-card")).toBeVisible();
    if (screen.name === "flashcards") await expect(page.getByTestId("flashcard")).toBeVisible();
    if (screen.name === "notebooks") await expect(page.locator(".notebook-tile")).toHaveCount(4);
    if (screen.name === "profile") await expect(page.getByRole("button", { name: VI["Save profile"] })).toBeVisible();
    if (screen.name === "video") await expect(page.getByText("I would like to make a reservation.", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
    // The agent starts by itself, so its mascot changes while this loop runs.
    for (const image of screen.name === "agent" || screen.name === "voice" ? [] : await page.locator(".dl-mascot-art:visible").all()) {
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    }
    // Only reads and the opening of a conversation happen on arrival.
    expect(writes.filter(path => (path.includes("/companion/") || path.includes("/agent/")) && !(screen.name === "agent" && path === `${API}/companion/sessions`))).toEqual([]);
    await page.screenshot({ path: info.outputPath(`${screen.name}-${width}-${colorScheme}.png`), fullPage: true, animations: "disabled" });
  });
}

test("landing signup link opens registration without contacting a learner API", async ({ page }) => {
  await fixture(page, false);
  await page.goto("/");
  await page.getByRole("link", { name: VI["Create your account"] }).first().click();
  await expect(page).toHaveURL(/\/signin\?mode=signup$/);
  await expect(page.getByRole("button", { name: VI["Sign up"], exact: true })).toBeVisible();
});

test("registration mode follows the URL when switching back to sign in", async ({ page }) => {
  await fixture(page, false);
  await page.goto("/signin?mode=signup");
  await page.getByRole("button", { name: VI["Already have an account? Sign in"] }).click();
  await expect(page).toHaveURL(/\/signin$/);
  await page.reload();
  await expect(page.getByRole("button", { name: VI["Sign in"], exact: true })).toBeVisible();
});

test("inline import on Home sends only the pasted URL", async ({ page }) => {
  await fixture(page, true);
  let sent: unknown;
  await page.route(`**${API}/library/videos`, route => {
    if (route.request().method() === "GET") return route.fulfill({ contentType: "application/json", body: JSON.stringify([video]) });
    sent = route.request().postDataJSON();
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(video) });
  });
  await page.goto("/home");
  await page.getByLabel(VI["Paste a YouTube link"]).fill("https://www.youtube.com/watch?v=jNQXAC9IVRw");
  await page.locator(".library-import-bar").getByRole("button").click();
  await expect.poll(() => sent).toEqual({ url: "https://www.youtube.com/watch?v=jNQXAC9IVRw" });
});

test("Profile theme choice overrides the device setting and survives a reload", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await fixture(page, true);
  await page.goto("/account");
  const background = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await expect(page.getByRole("button", { name: VI["Match device"] })).toHaveAttribute("aria-pressed", "true");
  const dark = await background();
  await page.getByRole("button", { name: VI["Light"], exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect.poll(background).not.toBe(dark);
  await page.screenshot({ path: info.outputPath("theme-light-over-dark-device.png") });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: VI["Light"], exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: VI["Match device"] }).click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.*/);
  await expect.poll(background).toBe(dark);
});
