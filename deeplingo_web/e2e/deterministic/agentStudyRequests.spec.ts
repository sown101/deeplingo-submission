import { expect, test } from "@playwright/test";

// What Tata asked to practise again stays in the agent screen: one chip in the toolbar, a short list, Set aside.
// Mocked API and socket: no live service.
test.use({ permissions: ["microphone"], launchOptions: { args: [
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
] } });

for (const [width, height] of [[390, 844], [1280, 800]]) {
  test(`practise-again list in the agent screen at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript(() => {
      localStorage.setItem("deeplingo.ui_language", "vi");
      localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({ access_token: "requests-dummy.header.token",
        token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
        user: { id: "requests-ci-user", aud: "authenticated", role: "authenticated", email: "requests@ci.invalid",
          app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" } }));
    });
    let items = [
      { id: "r1", kind: "grammar_redo", title: "Thì quá khứ đơn", reason: null, created_at: "2026-11-18T08:00:00Z" },
      { id: "r2", kind: "word_review", title: "itinerary", reason: null, created_at: "2026-11-18T08:01:00Z" },
    ];
    const unexpected: string[] = [], dismissed: string[] = [];
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      if (url.pathname.endsWith("/learner/me/language-profile")) return json({ learning_language: "en", support_language: "vi", is_complete: true });
      if (url.pathname.endsWith("/learner/me/agent/consent")) return json({ status: "granted", decided_at: "2026-10-31T00:00:00Z" });
      if (url.pathname.endsWith("/learner/me/agent/transcripts/consent")) return json({ status: "revoked", decided_at: "2026-11-07T00:00:00Z", active: false });
      if (url.pathname.endsWith("/learner/me/agent/study-requests")) {
        expect(url.searchParams.get("language")).toBe("en");
        return json({ items });
      }
      const dismiss = /\/learner\/me\/study-requests\/([^/]+)\/dismiss$/.exec(url.pathname);
      if (dismiss && route.request().method() === "POST") {
        dismissed.push(dismiss[1]);
        items = items.filter(item => item.id !== dismiss[1]);
        return json({ id: dismiss[1], status: "dismissed" });
      }
      if (url.pathname.endsWith("/learner/me/lists")) return json([]);
      if (url.pathname.endsWith("/learner/me/words")) return json({ words: [], summary: null });
      if (url.origin === "http://localhost:5173" && !url.pathname.startsWith("/api/")) return route.continue();
      unexpected.push(url.pathname); return route.abort();
    });
    await page.routeWebSocket("**/learner/me/companion/realtime", socket => socket.onMessage(raw => {
      if (typeof raw !== "string") return;
      const message = JSON.parse(raw);
      if (message.type === "start") socket.send(JSON.stringify({ type: "ready", max_seconds: 600, topic: "Travel", language_code: "en" }));
      if (message.type === "end") socket.send(JSON.stringify({ type: "ended", reason: "learner_ended", follow_ups: [] }));
    }));
    await page.goto("/agent?mode=voice");
    const chip = page.getByRole("button", { name: "Cần luyện lại (2)" });
    await expect(chip).toBeVisible();
    await chip.click();
    const list = page.getByRole("list", { name: "Cần luyện lại" });
    await expect(list).toContainText("Thì quá khứ đơn");
    await expect(list).toContainText("itinerary");
    await expect(list.getByRole("link", { name: "Luyện" })).toHaveAttribute("href", "/words/lists?tab=grammar");
    const box = await list.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`practise-again-${width}.png`) });
    await list.getByRole("button", { name: "Bỏ qua: itinerary" }).click();
    await expect(page.getByRole("button", { name: "Cần luyện lại (1)" })).toBeVisible();
    expect(dismissed).toEqual(["r2"]);
    expect(unexpected).toEqual([]);
  });
}
