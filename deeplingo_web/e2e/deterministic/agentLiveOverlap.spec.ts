import { expect, test, type Page } from "@playwright/test";

// The live voice screen with everything on it at once: the sentence, one growing hint card, a help card, the
// pronunciation note, the word chips and the opening choices. No two pieces of text may overlap, at any width.
test.use({ permissions: ["microphone"], launchOptions: { args: [
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
] } });

const WORDS = ["sightseeing", "delay", "itinerary", "book a room", "highlight", "reservation", "luggage", "souvenir"];
const LONG = "Last month I went to Da Nang with my whole family and we stayed in a small hotel near the beach for a week.";

async function open(page: Page, messages: (send: (event: unknown) => void, type: string) => void) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("deeplingo.ui_language", "vi");
    localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({ access_token: "overlap-dummy.header.token",
      token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: "overlap-ci-user", aud: "authenticated", role: "authenticated", email: "overlap@ci.invalid",
        app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" } }));
  });
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.endsWith("/learner/me/language-profile")) return json({ learning_language: "en", support_language: "vi", is_complete: true });
    if (url.pathname.endsWith("/learner/me/agent/consent")) return json({ status: "granted", decided_at: "2026-10-31T00:00:00Z" });
    if (url.pathname.endsWith("/learner/me/agent/transcripts/consent")) return json({ status: "revoked", decided_at: "2026-11-07T00:00:00Z", active: false });
    if (url.pathname.endsWith("/learner/me/lists")) return json([]);
    if (url.pathname.endsWith("/learner/me/words")) return json({ words: WORDS.map((text, index) => ({
      concept_id: `33333333-3333-4333-8333-${String(index + 1).padStart(12, "0")}`, text,
      language_code: "en", kind: "word", list: "saved", saved: true, status: "active", rung: [4, 3, 0, 0, 0][index % 5],
    })), summary: null });
    if (url.hostname === "localhost" && !url.pathname.startsWith("/api/")) return route.continue();
    return route.abort();
  });
  await page.routeWebSocket("**/learner/me/companion/realtime", socket => socket.onMessage(raw => {
    if (typeof raw !== "string") return;
    const type = JSON.parse(raw).type as string;
    messages(event => socket.send(JSON.stringify(event)), type);
  }));
}

/** Every piece of text on the stage as a box; any two that are neither nested nor apart are overlapping. */
async function overlaps(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const root = document.querySelector(".agent-voice")!;
    const boxes: { text: string; r: DOMRect; el: Element }[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const el = node.parentElement!;
      const text = (node.textContent ?? "").trim();
      if (!text || el.closest("details:not([open]) > :not(summary)") || el.closest(".sr-only")) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const client of Array.from(range.getClientRects())) {
        // Only what can be seen: text scrolled out of a scrolling ancestor is not painted over anything.
        let [left, top, right, bottom] = [client.left, client.top, client.right, client.bottom];
        for (let up: Element | null = el; up && up !== document.body; up = up.parentElement) {
          const style = getComputedStyle(up);
          if (style.overflowY === "visible" && style.overflowX === "visible") continue;
          const box = up.getBoundingClientRect();
          [left, top, right, bottom] = [Math.max(left, box.left), Math.max(top, box.top), Math.min(right, box.right), Math.min(bottom, box.bottom)];
        }
        const r = new DOMRect(left, top, right - left, bottom - top);
        if (r.width > 1 && r.height > 1 && getComputedStyle(el).visibility !== "hidden") boxes.push({ text, r, el });
      }
    }
    const found: string[] = [];
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const [a, b] = [boxes[i], boxes[j]];
      if (a.el === b.el) continue;
      const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
      const h = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      if (w > 2 && h > 3) found.push(`"${a.text.slice(0, 30)}" overlaps "${b.text.slice(0, 30)}"`);
    }
    return found;
  });
}

for (const [width, height] of [[390, 844], [320, 568], [360, 640], [820, 1000], [1180, 520], [1440, 900]]) {
  test(`live Agent ${width}x${height}: no text overlaps while a long hint, help, scores and choices are shown`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, (send, type) => {
      if (type === "start") {
        send({ type: "ready", max_seconds: 600, topic: "Travel", language_code: "en", mode: "open" });
        send({ type: "transcript", role: "companion", text: LONG });
        send({ type: "choices", items: [{ id: "video" }, { id: "words", count: 5 }, { id: "roleplay" }, { id: "free" }] });
      }
      if (type === "help") {
        send({ type: "hint", level: 3, question: "Bạn đã ở đâu trong chuyến đi đó và bạn thích điều gì nhất?",
          frame: "I stayed at ___ and I liked ___ because ___.", frame_reason: "Dùng quá khứ để kể lại chuyến đi.",
          model_sentence: "I stayed at a small hotel near the beach and I liked the food because it was fresh.",
          items: [{ id: "a", text: "book a room", meaning: "đặt phòng" }, { id: "b", text: "itinerary", meaning: "lịch trình" },
            { id: "c", text: "sightseeing", meaning: "tham quan" }] });
        send({ type: "pronunciation", turn: 1, overall: 72, weak_words: ["itinerary", "sightseeing", "reservation"] });
      }
      if (type === "suggest") send({ type: "suggestions", items: [
        { sentence: "I would like a window seat near the exit.", explanation: "Hỏi lịch sự về chỗ ngồi." },
        { sentence: "We stayed in a small hotel near the beach.", explanation: "Kể về nơi ở." },
        { sentence: "It was the best holiday I have ever had.", explanation: "Nói cảm xúc." }] });
    });
    await page.goto("/agent?mode=voice");
    await expect(page.locator(".agent-mic")).toBeVisible();
    await expect(page.locator(".agent-choices button").first()).toBeVisible();
    expect(await overlaps(page)).toEqual([]);
    await page.getByRole("button", { name: "Gợi ý", exact: true }).click();
    await page.getByRole("button", { name: "Ý tưởng", exact: true }).click();
    await page.getByRole("button", { name: "Giải thích", exact: true }).click();
    await page.locator("summary").filter({ hasText: "Chi tiết" }).click({ force: true });
    await expect(page.locator(".agent-hint-card")).toHaveCount(1);
    await expect(page.locator(".agent-pron")).toBeVisible();
    expect(await overlaps(page)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    // On a phone or a laptop the session controls stay on screen; on a very short window the page scrolls instead.
    if (height >= 640) {
      const controls = await page.locator(".agent-session-controls").boundingBox();
      expect(controls!.y + controls!.height).toBeLessThanOrEqual(height);
    }
  });
}
