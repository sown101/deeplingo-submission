import { chromium, expect, test, type Browser, type Page, type Route } from "@playwright/test";
import { browserLaunchOptions, workspace } from "../../scripts/m1_runtime_helpers.mjs";
import { progressBody } from "./progressFixture";

// Deterministic browser gate.
//
// Every backend request is answered from local fixtures mirroring the
// learner-safe DTO contracts; every external host (Supabase, YouTube, …)
// is ABORTED, proving these specs need no external system. The Supabase
// session is seeded into localStorage, so no auth network call occurs.

const API = "/api/v1/v3";
const JWT = "e2e-dummy-jwt.header.token";

const LIB_ID = "11111111-1111-1111-1111-111111111111";
const LIB_ID_FAILED = "99999999-9999-9999-9999-999999999999";
const VID_ID = "22222222-2222-2222-2222-222222222222";
const SEG_ID = "33333333-4444-5555-6666-777777777777";
const LO_ID = "55555555-6666-7777-8888-999999999999";
const QUESTION_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa";
const CONCEPT_ID = "53a24597-033f-461e-95f7-4c8e8ad02ed5";

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

function json(route: Route, body: unknown, status = 200): void {
  void route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

// The live harness opens the study part the server cut, as a learner does.
async function mockStudyParts(page: Page) {
  await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/parts", (route) => json(route, {
    transcript_id: SEG_ID, source: "ai",
    parts: [{ start_segment_id: SEG_ID, end_segment_id: SEG_ID, start_ms: 1200, end_ms: 7974, segment_count: 1, title: "One" }],
  }));
}

async function mockBackend(page: Page): Promise<string[]> {
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
        return json(route, progressBody({ heatmap, streak: { current: 3, longest: 3, active_days: heatmap.length },
          cards: [{ language_code: "en", total: 4, due: 2, new: 1, learning: 1, review: 2, relearning: 0 }] }));
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
async function seedSession(page: Page): Promise<void> {
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

test.describe("deterministic browser gate — unauthenticated", () => {
  test("protected routes redirect to sign-in without any backend", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/home");
    await expect(page).toHaveURL(/\/signin$/);
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
  });

  test("sign in with valid credentials routes through onboarding into Home", async ({ page }) => {
    await mockBackend(page);
    // Deterministic Supabase Auth response for the real GoTrueClient wiring.
    await page.route("**/ci-dummy.supabase.co/auth/v1/**", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
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
        }),
      });
    });
    await page.goto("/signin");
    await page.fill("#email", "e2e@ci.invalid");
    await page.fill("#password", "password-123456");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    // Profile is complete in the fixture, so the app lands on Home.
    await expect(page).toHaveURL(/\/home$/, { timeout: 15_000 });
    await expect(page.getByRole("heading", { name: "Home", level: 1 })).toBeVisible();
  });
});

test.describe("deterministic browser gate — signed in", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
    await mockBackend(page);
  });

  test("Home shows the video in progress without a suggestion list", async ({ page }) => {
    await page.goto("/home");
    await expect(page.getByRole("heading", { name: "Home", level: 1 })).toBeVisible();
    await expect(page.getByText("Chào bạn! Hôm nay mình có vài gợi ý nhỏ.")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Listen to the greeting" })).toHaveCount(0);
    await expect(page.getByText("Suggested for you")).toHaveCount(0);
    await expect(page.getByText("3-day streak")).toHaveCount(0);
    // The old cards are gone: the suggestions already cover them.
    await expect(page.getByRole("heading", { name: "Quick review" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Continue learning" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Continue watching" })).toHaveCount(0);
    // Nothing opens until the learner chooses; Resume opens the existing Watch screen.
    await expect(page).toHaveURL(/\/home$/);
    await page.getByRole("button", { name: "Resume this video" }).click();
    await expect(page).toHaveURL(new RegExp(`/library/videos/${LIB_ID}/watch$`));
  });

  test("Review is a study mode of a word set, reached from the notebook", async ({ page }) => {
    await page.goto("/home");
    // The old Review session stays retired, and Review is no longer a tab (2026-11-05).
    await expect(page.getByRole("link", { name: "Open Review" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Review", exact: true })).toHaveCount(0);
    // A level of the shelf chart is a word set too ("All words" was removed, 2026-11-14).
    await page.goto("/words?level=0");
    await page.getByRole("button", { name: "Review", exact: true }).click();
    // Retired study-plan/skill scores stay hidden; L4 exposes word-use progress.
    await expect(page.getByText(/Practice evidence/)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Today's plan" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Progress" })).toHaveCount(1);
    await page.getByRole("dialog", { name: "Review settings" }).getByRole("button", { name: "Start", exact: true }).click();
    await expect(page).toHaveURL(`/review/en?types=choice&concepts=${CONCEPT_ID}&back=%2Fwords%3Flevel%3D0`);
  });

  test("Profile menu changes languages and declared level without reminders in My words", async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 900 });
    let learning = "en", support = "vi", declared: string | null = null;
    const writes: unknown[] = [];
    await page.route(`**${API}/languages`, route => json(route, [
      { code: "en", name_en: "English", name_native: "English", script: "Latn", is_active: true, display_order: 1 },
      { code: "zh", name_en: "Chinese", name_native: "中文", script: "Hans", is_active: true, display_order: 2 },
      { code: "vi", name_en: "Vietnamese", name_native: "Tiếng Việt", script: "Latn", is_active: true, display_order: 3 },
    ]));
    await page.route(`**${API}/learner/me/initialize`, route => json(route, { user_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", profile_status: "reused" }));
    await page.route(`**${API}/learner/me/language-profile`, route => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON(); writes.push(body);
        learning = body.learning_language; support = body.support_language;
        if (body.declared_level !== undefined) declared = body.declared_level || null;
      }
      return json(route, { learning_language: learning, support_language: support, declared_level: declared, is_complete: true });
    });
    await page.route(`**${API}/learner/me/words?**`, route => json(route, { words: [], summary: null }));
    await page.goto("/words?level=0");
    await expect(page.getByRole("link", { name: "Set your level in Profile", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Account menu", exact: true }).click();
    await page.getByRole("menuitem", { name: "Profile", exact: true }).click();
    await page.getByRole("group", { name: "My level", exact: true }).getByRole("button", { name: "B1", exact: true }).click();
    await page.getByRole("button", { name: "Save profile", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Profile saved.");
    expect(writes.at(-1)).toEqual({ learning_language: "en", support_language: "vi", declared_level: "B1" });
    await page.goto("/words?level=0");
    await expect(page.getByRole("heading", { name: "Level: Seen", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Set your level in Profile", exact: true })).toHaveCount(0);
    await expect(page.getByLabel("New words per day", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Account menu", exact: true }).click();
    await page.getByRole("menuitem", { name: "Profile", exact: true }).click();
    await page.getByRole("group", { name: "Learning language", exact: true }).getByRole("button", { name: "Chinese", exact: true }).click();
    await expect(page.getByRole("group", { name: "My level", exact: true }).getByRole("button", { name: "Not set", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("group", { name: "Support language", exact: true }).getByRole("button", { name: "English", exact: true }).click();
    await page.getByRole("group", { name: "My level", exact: true }).getByRole("button", { name: "HSK3", exact: true }).click();
    await page.getByRole("button", { name: "Save profile", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Profile saved.");
    expect(writes.at(-1)).toEqual({ learning_language: "zh", support_language: "en", declared_level: "HSK3" });
    await page.reload();
    await expect(page.getByRole("group", { name: "My level", exact: true }).getByRole("button", { name: "HSK3", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("profile-settings.png"), fullPage: true });
    await page.getByRole("group", { name: "My level", exact: true }).getByRole("button", { name: "Not set", exact: true }).click();
    await page.getByRole("button", { name: "Save profile", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Profile saved.");
    expect(writes.at(-1)).toEqual({ learning_language: "zh", support_language: "en", declared_level: "" });
    await page.goto("/words?level=0");
    await expect(page.getByRole("link", { name: "Set your level in Profile", exact: true })).toHaveCount(0);
  });

  test("Notebooks share a saved word and each opens a review of its own words", async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const groupA = "55555555-5555-5555-5555-555555555555";
    const groupB = "66666666-6666-6666-6666-666666666666";
    const notebooks = [groupA, groupB].map((id, index) => ({
      id, language_code: "en", name: index === 0 ? "Travel" : "Exam", description: null, word_count: 1, waiting_count: 0,
    }));
    const scopes: string[] = [];
    await page.route(`**${API}/learner/me/lists**`, route => {
      const path = new URL(route.request().url()).pathname;
      if (path === `${API}/learner/me/lists`) return json(route, notebooks);
      const notebook = notebooks.find(item => path.endsWith(`/${item.id}`));
      if (!notebook) return route.fallback();
      return json(route, { ...notebook, waiting: [], words: [{ concept_id: CONCEPT_ID, text: "elephant",
        gloss: "con voi", status: "active", rung: 0, level_label: "A1", above_level: false }] });
    });
    await page.route(`**${API}/learner/me/review/en/due**`, route => {
      const url = new URL(route.request().url());
      scopes.push(url.searchParams.getAll("concept_ids").join(","));
      return json(route, { language_code: "en", due_count: 0, new_count: 1, cards: [{ concept_id: CONCEPT_ID, text: "elephant", reading: null,
        is_new: true, due_at: null, exercise: { type: "choice", prompt: { text: "elephant", reading: null, sentence: null,
          options: ["con voi", "con mèo", "con hổ"] } } }] });
    });
    await page.goto("http://localhost:5173/words/lists");
    await expect(page.getByRole("heading", { name: "Notebooks" })).toBeVisible();
    for (const notebook of notebooks) {
      await page.getByRole("link", { name: new RegExp(`^${notebook.name}`) }).click();
      await expect(page.getByText("elephant", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Review", exact: true }).click();
      await page.getByRole("dialog", { name: "Review settings" }).getByRole("button", { name: "Start", exact: true }).click();
      await expect(page).toHaveURL(`/review/en?types=choice&concepts=${CONCEPT_ID}&back=%2Fwords%2Flists%2F${notebook.id}`);
      await expect(page.getByRole("button", { name: "con voi", exact: true })).toBeVisible();
      await page.getByRole("link", { name: "Back" }).click();
      await expect(page).toHaveURL(`/words/lists/${notebook.id}`);
      await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Notebook", exact: true }).click();
    }
    // Each notebook reviews exactly its chosen words.
    expect([...new Set(scopes)]).toEqual([CONCEPT_ID]);
    await page.screenshot({ path: info.outputPath("notebooks-mobile.png"), fullPage: true, animations: "disabled" });
  });
  test("live harness selects a region, practises and finishes", async ({ page }) => {
    test.setTimeout(60000);
    const region = { transcript_id: SEG_ID, start_segment_id: SEG_ID, end_segment_id: SEG_ID,
      start_ms: 1200, end_ms: 7974, segment_count: 1, preparation: null };
    let selected = false;
    let practised = false;
    await page.route("**" + API + "/learner/me/library/videos", (route) => {
      if (route.request().method() === "POST") {
        expect(route.request().postDataJSON()).toEqual({ url: "https://youtu.be/jNQXAC9IVRw" });
        return json(route, { command_status: "accepted", item: { ...readyVideo, description: null, transcript_available: true } });
      }
      return json(route, [failedVideo, readyVideo]);
    });
    await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/workspace**", (route) => {
      if (route.request().method() === "PUT" && route.request().url().endsWith("/region")) {
        expect(route.request().postDataJSON()).toEqual({ start_segment_id: SEG_ID, end_segment_id: SEG_ID });
        selected = true;
      }
      return json(route, { library_item_id: LIB_ID, position_ms: null, region: selected ? region : null, updated_at: null });
    });
    await page.route("**" + API + "/learner/me/words", (route) => {
      expect(route.request().postDataJSON()).toEqual({ source: "occurrence", library_item_id: LIB_ID, learning_object_id: LO_ID,
        region_id: `${SEG_ID}_${SEG_ID}` });
      return json(route, { concept_id: CONCEPT_ID, language_code: "en", text: "elephant", kind: "word",
        gloss: "con voi", list: "saved", saved: true, save_source: "occurrence" });
    });
    await page.route("**/practice-events/dictation", (route) => {
      expect(selected).toBe(true);
      expect(route.request().postDataJSON().answer).toBe("Synthetic practice response");
      practised = true;
      return json(route, { status: "created" });
    });
    await page.route(/\/regions\/[^/]+\/result$/, (route) => {
      expect(practised).toBe(true);
      return json(route, { region_id: route.request().url().split("/regions/")[1].split("/")[0], practised: true,
        dictation_attempts: 1, dictation_sentences: 1, dictation_accuracy: 0, shadowing_attempts: 0,
        shadowing_sentences: 0, shadowing_average: null, questions_answered: 0, questions_correct: 0,
        lookups: 0, words_saved: 0 });
    });
    await page.goto("/home");
    await mockStudyParts(page);
    const result = await workspace(page, "https://youtu.be/jNQXAC9IVRw");
    expect(result).toMatchObject({ server_completed: true, dictation_sentences: 1, saved_words: 1 });
  });

  test("workspace region preparation shows pending and retryable failed states without blocking watching or practice", async ({ page }) => {
    test.setTimeout(45_000);
    let prepStatus = "pending";
    const regionData = (status: string, retryable: boolean) => ({
      transcript_id: SEG_ID,
      start_segment_id: SEG_ID,
      end_segment_id: SEG_ID,
      start_ms: 1200,
      end_ms: 7974,
      segment_count: 1,
      preparation: {
        region_preparation_id: "33333333-4444-5555-6666-777777777777",
        status,
        failure_code: status === "failed" ? "provider_temporary" : null,
        retryable,
        reset_at: null,
        usable_count: 1,
        questions_status: "ready",
      },
    });

    await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/workspace**", (route) => {
      if (route.request().method() === "PUT" && route.request().url().endsWith("/region")) {
        prepStatus = "ready";
        return json(route, { library_item_id: LIB_ID, position_ms: null, region: regionData("ready", false), updated_at: null });
      }
      return json(route, { library_item_id: LIB_ID, position_ms: null, region: regionData(prepStatus, true), updated_at: null });
    });

    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await expect(page.locator(".region-bar")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("status").filter({ hasText: /Preparing words for this part/ })).toBeVisible();

    // Player and Dictation remain fully accessible even while preparation is pending
    await expect(page.locator(".player-frame iframe")).toBeVisible();
    await page.getByRole("tab", { name: "Dictation" }).click();
    await expect(page.getByRole("button", { name: "Start dictation" })).toBeVisible();
  });

  test("changing region updates workspace and occurrences without leaking old region data", async ({ page }) => {
    test.setTimeout(45_000);
    const seg2 = "44444444-5555-6666-7777-888888888888";
    let activeSeg = SEG_ID;
    await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/workspace**", (route) => {
      if (route.request().method() === "PUT" && route.request().url().endsWith("/region")) {
        const body = route.request().postDataJSON() as { start_segment_id: string; end_segment_id: string };
        activeSeg = body.start_segment_id;
      }
      return json(route, {
        library_item_id: LIB_ID,
        position_ms: null,
        region: {
          transcript_id: activeSeg,
          start_segment_id: activeSeg,
          end_segment_id: activeSeg,
          start_ms: activeSeg === SEG_ID ? 1200 : 7974,
          end_ms: activeSeg === SEG_ID ? 7974 : 18881,
          segment_count: 1,
          preparation: null,
        },
        updated_at: null,
      });
    });

    await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/parts", (route) => json(route, {
      transcript_id: SEG_ID, source: "ai", parts: [
        { start_segment_id: SEG_ID, end_segment_id: SEG_ID, start_ms: 1200, end_ms: 7974, segment_count: 1, title: "One" },
        { start_segment_id: seg2, end_segment_id: seg2, start_ms: 7974, end_ms: 18881, segment_count: 1, title: "Two" },
      ] }));
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    const parts = page.getByRole("group", { name: "Change part" });
    await expect(parts).toBeVisible();

    await parts.getByRole("button", { name: /^Part 2:/ }).click();

    // Workspace reflects the new segment range
    await expect(parts.getByRole("button", { name: /^Part 2:/ })).toHaveAttribute("aria-pressed", "true");
    expect(activeSeg).toBe(seg2);
  });

  test("reloading /watch restores saved region and player position", async ({ page }) => {
    test.setTimeout(45_000);
    await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/workspace**", (route) => {
      return json(route, {
        library_item_id: LIB_ID,
        position_ms: 5400,
        region: {
          transcript_id: SEG_ID,
          start_segment_id: SEG_ID,
          end_segment_id: SEG_ID,
          start_ms: 1200,
          end_ms: 7974,
          segment_count: 1,
          preparation: null,
        },
        updated_at: "2026-10-23T10:00:00Z",
      });
    });

    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await expect(page.locator(".region-bar").getByRole("button", { name: "Finish" })).toBeVisible();

    // Reload page: saved region and position are preserved from server
    await page.reload();
    await expect(page.locator(".region-bar").getByRole("button", { name: "Finish" })).toBeVisible();
    await expect(page.locator(".player-frame iframe")).toBeVisible();
  });

  // A part nothing was practised in is a valid answer: the card says so and shows no error.
  test("part result of an untouched part says nothing was practised, not a failure", async ({ page }) => {
    const region = { transcript_id: SEG_ID, start_segment_id: SEG_ID, end_segment_id: SEG_ID,
      start_ms: 1200, end_ms: 7974, segment_count: 1, preparation: null };
    await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/workspace**", (route) =>
      json(route, { library_item_id: LIB_ID, position_ms: null, region, updated_at: null }));
    await page.route(/\/regions\/[^/]+\/result$/, (route) =>
      json(route, { region_id: `${SEG_ID}_${SEG_ID}`, practised: false, dictation_attempts: 0, dictation_sentences: 0,
        dictation_accuracy: null, shadowing_attempts: 0, shadowing_sentences: 0, shadowing_average: null,
        questions_answered: 0, questions_correct: 0, lookups: 0, words_saved: 0 }));
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await expect(page.locator(".region-bar")).toBeVisible({ timeout: 15_000 });
    await page.locator(".region-bar").getByRole("button", { name: "Finish" }).click();
    await expect(page.locator(".region-result")).toContainText("Nothing practised in this part yet.");
    await expect(page.getByText("We could not load the result. Please try again.")).toHaveCount(0);
  });

  test("HTTP 500 on the part result shows an error and no result lines", async ({ page }) => {
    test.setTimeout(45_000);
    await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/workspace**", (route) => {
      return json(route, {
        library_item_id: LIB_ID, position_ms: null, updated_at: null,
        region: { transcript_id: SEG_ID, start_segment_id: SEG_ID, end_segment_id: SEG_ID, start_ms: 1200,
          end_ms: 7974, segment_count: 1, preparation: null },
      });
    });
    await page.route(/\/regions\/[^/]+\/result$/, (route) => json(route, { detail: { code: "result_refused" } }, 500));

    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await expect(page.locator(".region-bar")).toBeVisible({ timeout: 15_000 });
    await page.locator(".region-bar").getByRole("button", { name: "Finish" }).click();

    await expect(page.locator(".region-result__lines")).toHaveCount(0);
    await expect(page.getByText("We could not load the result. Please try again.")).toBeVisible();
  });

  test("Home lists the videos, opens a ready one in Watch and retries only retryable failures", async ({ page }) => {
    await page.goto("/home");
    await expect(page).toHaveURL(/\/home$/);
    const videos = page.getByRole("region", { name: "Your videos" });
    await expect(videos.getByText("Me at the zoo")).toBeVisible();
    await expect(videos.getByText("Ready for practice")).toBeVisible();
    await expect(videos.getByRole("link", { name: "Me at the zoo" })).toHaveAttribute("href", `/library/videos/${LIB_ID}/watch`);
    await expect(videos.getByText("The video is unavailable")).toBeVisible();
    await expect(videos.getByRole("button", { name: /^Retry$/ })).toHaveCount(0);
  });

  test("retired Learn route no longer opens the video learning page", async ({ page }) => {
    await page.goto(`/library/videos/${LIB_ID}/learn`);
    await expect(page).toHaveURL(/\/home$/);
    await expect(page.getByRole("heading", { name: "Learn from this video", exact: true })).toHaveCount(0);
  });

  test("Watch renders the player and trusted transcript synchronization surface", async ({ page }) => {
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    const frame = page.locator(".player-frame iframe");
    await expect(frame).toBeVisible();
    // The iframe source must be constrained to the trusted YouTube embed for
    // the validated backend-provided video id — never an arbitrary URL.
    const src = await frame.getAttribute("src");
    expect(src).toMatch(/^https:\/\/www\.youtube-nocookie\.com\/embed\/jNQXAC9IVRw\?/);
    expect(src).toContain("enablejsapi=1");
    const rows = page.locator(".transcript-row");
    await expect(rows).toHaveCount(2);
    const occurrence = page.locator(".occurrence");
    await expect(occurrence).toHaveCount(1);
    await expect(occurrence).toHaveText("Elephants");
    await expect(page.getByText("Voi có thể sống tới bảy mươi tuổi.")).toBeVisible();
    // Server-provided translation carries its support language code.
    await expect(page.locator(".translation").first()).toHaveAttribute("lang", "vi");
    // Seek on row click issues a player seek command via postMessage; the
    // row is a button-like element wired to the persisted start_ms.
    await rows.nth(1).click();
  });

  test("Watch hosts dictation and shadowing beside the same player", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/library/videos/${LIB_ID}/watch?mode=dictation`);
    await expect(page.getByRole("tab", { name: "Dictation", selected: true })).toBeVisible();
    await expect(page.locator(".player-frame iframe")).toHaveCount(1);
    await page.getByRole("button", { name: "Hard · type it" }).click();
    await page.getByRole("button", { name: "Start dictation" }).click();
    await page.getByRole("button", { name: "Show hint" }).click();
    await expect(page.locator(".dictation-hint .hint-word")).not.toHaveCount(0);
    await page.screenshot({ path: "test-results/watch-dictation.png" });
    await page.getByRole("tab", { name: "Shadowing" }).click();
    await expect(page).toHaveURL(/mode=shadowing/);
    await expect(page.getByRole("button", { name: "Record" })).toBeVisible();
    await expect(page.locator(".player-frame iframe")).toHaveCount(1);
    await page.getByRole("tab", { name: "Transcript", exact: true }).click();
    await expect(page.getByRole("tab", { name: "Companion" })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Transcript" })).toBeVisible();
    await expect(page.locator(".transcript-row")).toHaveCount(2);
    await expect(page.locator(".player-frame iframe")).toHaveCount(1);
  });

  test("Watch Questions are checked by the server and point to the sentence (M1 S6)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/library/videos/${LIB_ID}/watch?mode=questions`);
    await expect(page.getByRole("tab", { name: "Questions", selected: true })).toBeVisible();
    await page.getByRole("button", { name: "Khoảng 7 năm" }).click();
    await expect(page.getByText("Not quite. The answer is “Khoảng 70 năm”.")).toBeVisible();
    await expect(page.locator(".question-result q")).toHaveText("live to seventy years old");
    await expect(page.getByRole("button", { name: "Play this sentence" })).toBeVisible();
    await page.screenshot({ path: "test-results/watch-questions.png" });
    await expect(page.locator(".player-frame iframe")).toHaveCount(1);
  });

  test("Finish shows the part result read from the learning log", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const region = { transcript_id: SEG_ID, start_segment_id: SEG_ID, end_segment_id: SEG_ID, start_ms: 1200,
                     end_ms: 7974, segment_count: 1, preparation: null };
    // Registered after the shared mocks, so these answer first.
    await page.route(`**${API}/learner/me/library/videos/${LIB_ID}/workspace`, (route) =>
      json(route, { library_item_id: LIB_ID, position_ms: null, region, updated_at: null }));
    await page.route(`**${API}/learner/me/library/videos/${LIB_ID}/regions/${SEG_ID}_${SEG_ID}/result`, (route) =>
      json(route, { region_id: `${SEG_ID}_${SEG_ID}`, practised: true, dictation_attempts: 2, dictation_sentences: 1,
        dictation_accuracy: 90, shadowing_attempts: 1, shadowing_sentences: 1, shadowing_average: 82,
        questions_answered: 2, questions_correct: 2, lookups: 1, words_saved: 1 }));
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await page.getByRole("button", { name: "Finish" }).click();
    await expect(page.getByRole("heading", { name: "Result for 00:01–00:07" })).toBeVisible();
    await expect(page.getByText("2 of 2 right")).toBeVisible();
    await expect(page.getByText("Average score 82, 1 attempts")).toBeVisible();
    // One Tata: the page launcher talks about the part; the result sits in the right panel, clear of it.
    await expect(page.getByRole("link", { name: /with Tata/ })).toHaveCount(0);
    const talk = page.locator(".agent-launcher").getByRole("link", { name: /^Talk about (part \d+|this part)$/ });
    await expect(talk).toBeVisible();
    const result = await page.locator(".region-result").boundingBox();
    const launcher = await page.locator(".agent-launcher").boundingBox();
    expect(result!.x + result!.width <= launcher!.x || result!.y + result!.height <= launcher!.y
      || launcher!.x + launcher!.width <= result!.x).toBe(true);
    await page.screenshot({ path: "test-results/watch-region-result.png" });
  });

  for (const width of [1440, 1280, 390]) {
    test(`Watch practice panel never scrolls sideways and the part result clears Tata at ${width}px`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 900 });
      const region = { transcript_id: SEG_ID, start_segment_id: SEG_ID, end_segment_id: SEG_ID, start_ms: 1200,
                       end_ms: 7974, segment_count: 1, preparation: null };
      await page.route(`**${API}/learner/me/library/videos/${LIB_ID}/workspace`, (route) =>
        json(route, { library_item_id: LIB_ID, position_ms: null, region, updated_at: null }));
      await page.route(`**${API}/learner/me/library/videos/${LIB_ID}/regions/${SEG_ID}_${SEG_ID}/result`, (route) =>
        json(route, { region_id: `${SEG_ID}_${SEG_ID}`, practised: true, dictation_attempts: 2, dictation_sentences: 1,
          dictation_accuracy: 90, shadowing_attempts: 1, shadowing_sentences: 1, shadowing_average: 82,
          questions_answered: 2, questions_correct: 2, lookups: 1, words_saved: 1 }));
      await page.goto(`/library/videos/${LIB_ID}/watch?mode=dictation`);
      await page.getByRole("button", { name: "Start dictation" }).click();
      const panel = page.locator(".watch-right > .mode-panel");
      await expect(panel).toBeVisible();
      const sideways = () => panel.evaluate((node) => node.scrollWidth - node.clientWidth);
      expect(await sideways()).toBeLessThanOrEqual(0);
      await page.getByRole("button", { name: "Part result" }).click();
      const result = page.locator(".region-result");
      await expect(result.getByText("Average score 82, 1 attempts")).toBeVisible();
      await result.scrollIntoViewIfNeeded();
      expect(await page.locator(".watch-right > .mode-panel").evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(0);
      await expect(page.locator(".agent-launcher").getByRole("link", { name: /^Talk about (part \d+|this part)$/ })).toBeVisible();
      await expect(page.getByRole("link", { name: /with Tata/ })).toHaveCount(0);
      const box = (await result.boundingBox())!;
      const launcher = (await page.locator(".agent-launcher").boundingBox())!;
      const next = (await result.getByRole("button", { name: /^Next|You reached/ }).or(result.getByText("You reached the end of the video.")).first().boundingBox())!;
      const overlaps = (a: typeof box, b: typeof box) =>
        a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
      expect(overlaps(next, launcher)).toBe(false);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath(`watch-result-${width}.png`) });
    });
  }

  for (const width of [390, 1180, 1440]) {
    test(`Watch uses one Tata and the reference subtitle placement at ${width}px`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto(`/library/videos/${LIB_ID}/watch`);
      await page.locator(".transcript-row").first().waitFor();
      const player = await page.locator(".player-frame").boundingBox();
      const transcript = await page.getByRole("region", { name: "Transcript", exact: true }).boundingBox();
      if (width >= 700) {
        expect(transcript!.x).toBeGreaterThanOrEqual(player!.x + player!.width);
        const tabs = await page.getByRole("tablist", { name: "Workspace tools" }).boundingBox();
        expect(tabs!.y).toBeCloseTo(player!.y, 0);
        expect(transcript!.y).toBeGreaterThanOrEqual(tabs!.y + tabs!.height);
      } else expect(transcript!.y).toBeGreaterThanOrEqual(player!.y + player!.height);
      await expect(page.getByRole("tab", { name: "Companion" })).toHaveCount(0);
      await expect(page.locator(".watch-layout .companion-conversation, .watch-layout .realtime-screen")).toHaveCount(0);
      await expect(page.locator(".agent-launcher")).toHaveCount(1);
      await page.screenshot({ path: info.outputPath("watch-reference-layout.png"), fullPage: true });
      await page.getByRole("button", { name: "Open agent", exact: true }).click();
      const panel = page.getByRole("dialog", { name: "Agent conversation" });
      await expect(panel.getByRole("button", { name: "Start talking", exact: true })).toBeVisible();
      await expect(page.locator(".realtime-screen")).toHaveCount(1);
      await page.getByRole("button", { name: "Close agent", exact: true }).click();
      await expect(page.locator(".companion-conversation, .realtime-screen")).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }

  test("desktop Watch columns align bottom edges (density)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await page.locator(".transcript-row").first().waitFor();
    const alignment = await page.evaluate(() => {
      const left = document.querySelector(".watch-left")?.getBoundingClientRect().bottom ?? 0;
      const right = document.querySelector(".watch-right")?.getBoundingClientRect().bottom ?? 0;
      return Math.abs(left - right);
    });
    expect(alignment).toBeLessThanOrEqual(2);
  });

  test("Concept sheet renders learner-safe fields from a trusted occurrence", async ({ page }) => {
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await page.locator(".occurrence").click();
    const sheet = page.getByRole("dialog", { name: "Concept" });
    await expect(sheet.getByText("con voi")).toBeVisible();
    await expect(sheet.getByText("Meaning in context")).toBeVisible();
    // No authority fields ever appear.
    await expect(sheet.getByText(/concept_id/i)).toHaveCount(0);
    await expect(sheet.getByText(/sense_key/i)).toHaveCount(0);
    await expect(sheet.getByText(/mastery/i)).toHaveCount(0);
  });

  test("Concept sheet closes on Escape and restores focus to the opener", async ({ page }) => {
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await page.locator(".occurrence").click();
    const sheet = page.getByRole("dialog", { name: "Concept" });
    await expect(sheet).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    // Focus returns to the trusted occurrence that opened the sheet.
    await expect(page.locator(".occurrence")).toBeFocused();
  });

  test("Library has one import form, supports Enter and preserves the URL after an API error", async ({ page }) => {
    const sent: unknown[] = [];
    await page.route("**" + API + "/learner/me/library/videos", route => {
      expect(route.request().headers().authorization).toBe(`Bearer ${JWT}`);
      if (route.request().method() === "GET") return json(route, [readyVideo, failedVideo]);
      sent.push(route.request().postDataJSON());
      if (sent.length === 1) return route.fulfill({ status: 400, contentType: "application/json",
        body: JSON.stringify({ detail: { code: "invalid_video_url", message: "private diagnostic" } }) });
      return route.fulfill({ status: 202, contentType: "application/json",
        body: JSON.stringify({ command_status: "accepted", item: { ...readyVideo, description: null, transcript_available: true } }) });
    });
    await page.goto("/home");
    await expect(page.getByRole("button", { name: "Add video" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add", exact: true })).toHaveCount(1);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const input = page.getByLabel("Paste a YouTube link");
    await input.fill("https://youtu.be/jNQXAC9IVRw");
    await input.press("Enter");
    await expect(page.getByRole("alert").filter({ hasText: "That link is not a valid YouTube URL." }))
      .toHaveText("That link is not a valid YouTube URL.");
    await expect(input).toHaveValue("https://youtu.be/jNQXAC9IVRw");
    await expect(page.getByText("private diagnostic")).toHaveCount(0);
    await expect(input).toBeEnabled();
    await input.press("Enter");
    await expect(input).toHaveValue("");
    expect(sent).toEqual([{ url: "https://youtu.be/jNQXAC9IVRw" }, { url: "https://youtu.be/jNQXAC9IVRw" }]);
  });

  test("learner statistics render from read-only server projections", async ({ page }) => {
    await page.clock.setFixedTime(new Date(2026, 9, 14, 12));
    await page.goto("/home");
    await expect(page.getByRole("img", { name: /practice attempts in the last \d+ weeks/ })).toBeVisible();
    await expect(page.locator(".act-heatmap__grid .act-cell").first()).toBeVisible();
    await expect(page.getByRole("list", { name: "4 cards" })).toBeVisible();
    await expect(page.getByText("3-day streak")).toHaveCount(0);
  });

  test("the Progress tab shows the learner's record", async ({ page }) => {
    await page.goto("/progress");
    await expect(page.getByRole("heading", { name: "Progress", level: 1 })).toBeVisible();
    await expect(page.getByText("4 samples")).toHaveCount(0);
  });
  for (const [width, path] of [[1280, "/home"], [390, "/home"], [1280, `/library/videos/${LIB_ID}/watch`], [390, `/library/videos/${LIB_ID}/watch`]] as const) {
    test(`Tata panel follows the reference sheet and side panel at ${path}, ${width}px`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(path);
      await page.getByRole("button", { name: "Open agent", exact: true }).click();
      const panel = page.getByRole("dialog", { name: "Agent conversation" });
      await expect(panel.getByRole("button", { name: "Start talking", exact: true })).toBeVisible();
      await expect(panel).toHaveCSS("transform", /^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
      const content = await page.getByRole("main").boundingBox(), box = await panel.boundingBox();
      expect(content).not.toBeNull(); expect(box).not.toBeNull();
      expect(box!.width).toBe(width > 900 ? 384 : width);
      expect(box!.x).toBe(width > 900 ? width - 24 - 384 : 0);
      expect(box!.y + box!.height).toBeCloseTo(width > 900 ? 876 : 900, 0);
      if (width > 900) expect(box!.y).toBe(84);
      else expect(box!.height).toBeGreaterThanOrEqual(360);
      await expect(panel.getByRole("link", { name: "Open full conversation" })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath("agent-panel.png"), fullPage: true });
      await page.keyboard.press("Escape"); await expect(panel).toHaveCount(0);
    });
  }

  test("agent keeps what the agent knows about you reachable", async ({ page }) => {
    await page.route("**/learner/me/agent/consent", route => json(route, { status: "granted", decided_at: "2026-10-29T10:00:00Z" }));
    await page.route("**/learner/me/agent/signals", route => json(route, { signals: [] }));
    await page.route("**/learner/me/agent/memory", route => json(route, { items: [] }));
    await page.route("**/learner/me/lists", route => json(route, []));
    await page.goto("/agent?mode=voice");
    await expect(page.getByRole("link", { name: "What the agent knows about you", exact: true })).toHaveCount(0);
    await page.goto("/account");
    await expect(page).toHaveURL(/\/account$/);
    await expect(page.getByRole("heading", { name: "Voice and privacy", exact: true })).toBeVisible();
    await expect(page.getByRole("switch", { name: "Voice processing", exact: true })).toBeVisible();
  });


});

test.describe("narrow viewport (mobile web)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ page }) => {
    // Seed the authenticated session exactly like the desktop specs.
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
    await mockBackend(page);
  });

  test("Watch collapses to a single column without horizontal overflow", async ({ page }) => {
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await expect(page.locator(".player-frame iframe")).toBeVisible();
    await expect(page.locator(".transcript-row").first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("Dictation on a phone has no horizontal overflow", async ({ page }) => {
    await page.goto(`/library/videos/${LIB_ID}/watch?mode=dictation`);
    await page.getByRole("button", { name: "Start dictation" }).click();
    await expect(page.getByLabel("Words")).toBeVisible();
    await page.screenshot({ path: "test-results/watch-dictation-phone.png", fullPage: true });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("Home video cards stack without horizontal overflow", async ({ page }) => {
    await page.goto("/home");
    await expect(page.getByRole("region", { name: "Your videos" }).getByText("Me at the zoo")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    const account = await page.getByRole("button", { name: "Account menu", exact: true }).boundingBox();
    const nav = await page.getByRole("navigation", { name: "Primary" }).boundingBox();
    expect(account!.y).toBeLessThan(64);
    expect(nav!.y).toBeGreaterThan(account!.y + account!.height);
    await expect(page.getByRole("menuitem", { name: "Sign out" })).toHaveCount(0);
    await page.getByRole("button", { name: "Account menu", exact: true }).click();
    await expect(page.getByRole("menuitem", { name: "Sign out", exact: true })).toBeVisible();
  });

});

test.describe("extra-narrow viewport (320px, long localized text)", () => {
  test.use({ viewport: { width: 320, height: 700 } });

  test.beforeEach(async ({ page }) => {
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
    await mockBackend(page);
    // Long localized title including an unbroken token to stress wrapping.
    await page.route("**/api/v1/v3/learner/me/library/videos", (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/learner/me/library/videos") && route.request().method() === "GET") {
        void route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              ...readyVideo,
              title:
                "Eine sehr lange lokalisierte videoaufzeichnungssitzungsdokumentationsüberschrift",
            },
          ]),
        });
        return;
      }
      void route.continue();
    });
  });

  test("Library long title wraps without horizontal overflow", async ({ page }) => {
    await page.goto("/home");
    await expect(page.getByText(/Eine sehr lange lokalisierte/)).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("Watch long title wraps without horizontal overflow", async ({ page }) => {
    await page.goto(`/library/videos/${LIB_ID}/watch`);
    await expect(page.locator(".transcript-row").first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});


// The live harness helper itself, Companion branch, against the product's real client routes:
// POST /learner/me/companion/sessions, POST /learner/me/companion/turns, then the part result.
test.describe("live harness Companion helper (fake microphone)", () => {
  // test.use(launchOptions) cannot be scoped to a describe, so the same options the live runner uses launch here.
  const region = { transcript_id: SEG_ID, start_segment_id: SEG_ID, end_segment_id: SEG_ID,
    start_ms: 1200, end_ms: 7974, segment_count: 1, preparation: null };

  async function mockCompanionRun(page: Page, resultFor: (turns: number) => Record<string, unknown>) {
    const log: string[] = [];
    let turns = 0;
    let selected = false;
    const turnBody = (n: number, transcript: string | null) => ({
      session_ticket: "signed.ticket", expires_at: "2026-10-19T10:00:00Z", turn: n, max_turns: 30, finished: false,
      language_code: "en", support_language_code: "vi", entry: "video", library_item_id: LIB_ID, topic: "Zoo",
      learner_transcript: transcript, reply: n === 0 ? "What happens in this part?" : "Nice, tell me more.",
      reply_support: "V�ng.", hints: { question: null, items: [], frame: null, model_sentence: null },
      correction: null, used_items: [], next: "continue", audio: null, audio_status: "unavailable",
      memory_status: "off", practice_suggestion: null,
    });
    await page.route("**" + API + "/learner/me/library/videos", (route) =>
      route.request().method() === "POST"
        ? json(route, { command_status: "accepted", item: { ...readyVideo, description: null, transcript_available: true } })
        : json(route, [readyVideo]));
    await page.route("**" + API + "/learner/me/library/videos/" + LIB_ID + "/workspace**", (route) => {
      if (route.request().method() === "PUT" && route.request().url().endsWith("/region")) selected = true;
      return json(route, { library_item_id: LIB_ID, position_ms: null, region: selected ? region : null, updated_at: null });
    });
    await page.route("**" + API + "/learner/me/words", (route) =>
      json(route, { concept_id: CONCEPT_ID, language_code: "en", text: "elephant", kind: "word",
        gloss: "con voi", list: "saved", saved: true, save_source: "occurrence" }));
    await page.route("**" + API + "/learner/me/companion/sessions", (route) => {
      expect(route.request().method()).toBe("POST");
      // The embed has not started: the selected study region supplies context on the server.
      expect(route.request().postDataJSON()).toEqual({ entry: "video", library_item_id: LIB_ID });
      log.push("sessions");
      return json(route, turnBody(0, null));
    });
    // The conversation takes its turns on /turns/stream: the turn as one NDJSON line, then its speech, then done.
    await page.route("**" + API + "/learner/me/companion/turns/stream", (route) => {
      expect(route.request().headers()["content-type"]).toContain("multipart/form-data");
      log.push("turns");
      turns += 1;
      return route.fulfill({ contentType: "application/x-ndjson",
        body: JSON.stringify({ type: "turn", turn: turnBody(turns, "I see elephants") }) + "\n"
          + JSON.stringify({ type: "done" }) + "\n" });
    });
    await page.route("**" + API + "/learner/me/companion/finish", (route) => json(route, {}));
    await page.route(/\/regions\/[^/]+\/result$/, (route) => {
      log.push("result");
      return json(route, { region_id: `${SEG_ID}_${SEG_ID}`, practised: false, dictation_attempts: 0, dictation_sentences: 0,
        dictation_accuracy: null, shadowing_attempts: 0, shadowing_sentences: 0, shadowing_average: null,
        questions_answered: 0, questions_correct: 0, lookups: 0, words_saved: 0, ...resultFor(turns) });
    });
    return log;
  }

  let browser: Browser;
  let page: Page;
  test.beforeEach(async () => {
    browser = await chromium.launch(browserLaunchOptions());
    page = await (await browser.newContext({ baseURL: "http://localhost:5173", permissions: ["microphone"] })).newPage();
    await seedSession(page);
    await mockBackend(page);
    await mockStudyParts(page);
  });
  test.afterEach(async () => { await browser.close(); });

  test("opens the conversation, sends a learner turn, and then reads the part result", async () => {
    test.setTimeout(60_000);
    const log = await mockCompanionRun(page, () => ({}));
    await page.goto("/home");
    const result = await workspace(page, "https://youtu.be/jNQXAC9IVRw", { tool: "companion" });
    expect(log).toEqual(["sessions", "turns", "result"]);
    expect(result).toMatchObject({ server_completed: true, practice_tool: "companion", companion_finish_confirmed: true,
      dictation_sentences: 0 });
    await expect(page.locator(".region-result")).toContainText("Nothing practised in this part yet.");
  });

  test("all-tools helper counts every practice tool and a real Companion turn", async () => {
    test.setTimeout(60_000);
    const log = await mockCompanionRun(page, () => ({
      practised: true, dictation_attempts: 1, dictation_sentences: 1, shadowing_attempts: 1, shadowing_sentences: 1,
      questions_answered: 1,
    }));
    await page.route("**/practice-events/dictation", (route) => {
      log.push("dictation");
      return json(route, { id: route.request().postDataJSON().id, status: "created", words_right: 1, words_total: 10 });
    });
    await page.route("**/shadowing/assessments", (route) => {
      expect(route.request().headers()["content-type"]).toContain("multipart/form-data");
      log.push("shadowing");
      return json(route, { segment_id: SEG_ID, reference_text: transcript.segments[0].text, recognized_text: "Elephants",
        band: "good", scores: { pronunciation: 80, accuracy: 80, fluency: 80, completeness: 80, prosody: null },
        words: [], attempt_duration_ms: 1500, reference_duration_ms: 6774, spoken_duration_ms: 1200 });
    });
    await page.route("**/region-questions/*/answer", (route) => {
      log.push("question");
      return json(route, { question_id: QUESTION_ID, selected_option: 0, correct: false, correct_index: 1,
        evidence_segment_id: SEG_ID, evidence_quote: "seventy years old", explanation: "Source sentence." });
    });
    await page.goto("/home");
    const result = await workspace(page, "https://youtu.be/jNQXAC9IVRw", { tool: "all" });
    expect(log).toEqual(["dictation", "shadowing", "question", "sessions", "turns", "result"]);
    expect(result).toMatchObject({ server_completed: true, practice_tool: "all", dictation_sentences: 1,
      shadowing_sentences: 1, questions_answered: 1, companion_finish_confirmed: true });
  });

});


// Same exported entry function as the separate zero-AI smoke, with real UI interactions.