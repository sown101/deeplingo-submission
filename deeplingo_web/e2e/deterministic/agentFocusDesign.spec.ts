import { expect, test } from "@playwright/test";

test.use({ permissions: ["microphone"], launchOptions: { args: [
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
] } });

const WORDS = ["sightseeing", "delay", "itinerary", "book a room", "highlight"];
for (const [width, height, portraitY, startY] of [[390, 844, 330, 642], [1180, 820, 306, 694], [1440, 900, 350, 738]]) {
  for (const theme of ["light", "dark"] as const) {
    test(`focused Agent ${width}px ${theme}: reference layout and reachable session controls`, async ({ page }, info) => {
      await page.setViewportSize({ width, height });
      await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
      await page.addInitScript(() => {
        localStorage.setItem("deeplingo.ui_language", "vi");
        localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({ access_token: "focus-dummy.header.token",
          token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
          user: { id: "focus-ci-user", aud: "authenticated", role: "authenticated", email: "focus@ci.invalid",
            app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" } }));
      });
      const unexpected: string[] = [];
      await page.route("**/*", route => {
        const url = new URL(route.request().url());
        const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
        if (url.pathname.endsWith("/learner/me/language-profile")) return json({ learning_language: "en", support_language: "vi", is_complete: true });
        if (url.pathname.endsWith("/learner/me/agent/consent")) return json({ status: "granted", decided_at: "2026-10-31T00:00:00Z" });
        if (url.pathname.endsWith("/learner/me/agent/study-requests")) return json({ items: [] });
        if (url.pathname.endsWith("/learner/me/agent/transcripts/consent")) return json({ status: "revoked", decided_at: "2026-11-07T00:00:00Z", active: false });
        if (url.pathname.endsWith("/learner/me/lists")) return json([]);
        if (url.pathname.endsWith("/learner/me/companion/scenarios")) return json([
          { id: "hotel", title: "Missing reservation", context: "The reservation is missing.",
            roles: ["Guest", "Receptionist"], goals: ["Confirm your booking.", "Offer a solution."] },
        ]);
        if (url.pathname.endsWith("/learner/me/words")) return json({ words: WORDS.map((text, index) => ({
          concept_id: `33333333-3333-4333-8333-${String(index + 1).padStart(12, "0")}`, text,
          language_code: "en", kind: "word", list: "saved", saved: true, status: "active", rung: [4, 3, 0, 0, 0][index],
        })), summary: null });
        if (url.origin === "http://localhost:5173" && !url.pathname.startsWith("/api/")) return route.continue();
        unexpected.push(url.pathname); return route.abort();
      });
      await page.routeWebSocket("**/learner/me/companion/realtime", socket => socket.onMessage(raw => {
        if (typeof raw !== "string") return;
        const message = JSON.parse(raw);
        if (message.type === "start") {
          socket.send(JSON.stringify({ type: "ready", max_seconds: 600, topic: "Travel", language_code: "en" }));
          socket.send(JSON.stringify({ type: "transcript", role: "learner", text: "Last month I went to Da Nang with my family." }));
        }
        if (message.type === "help") socket.send(JSON.stringify({ type: "hint", level: 1, question: "Where did you stay?",
          items: [{ id: "book", text: "book a room", meaning: "đặt phòng" }] }));
        if (message.type === "end") socket.send(JSON.stringify({ type: "ended", reason: "learner_ended", follow_ups: [] }));
      }));
      await page.goto("/agent?mode=voice");
      await expect(page.locator(".topbar")).toBeHidden();
      await expect(page.locator(".agent-practice-modes a")).toHaveCount(0);
      await expect(page.locator(".agent-mic")).toBeVisible();
      await page.locator(".agent-live-tools > button").first().click();
      await expect(page.locator(".agent-hint-card")).toContainText("book a room");
      const controls = await page.locator(".agent-session-controls").boundingBox();
      expect(controls!.y + controls!.height).toBeLessThanOrEqual(height - 31);
      await expect(page.locator(".agent-session-controls button:visible")).toHaveCount(2);
      for (const button of await page.locator(".agent-session-controls button:visible").all()) {
        expect(await button.evaluate(element => {
          const r = element.getBoundingClientRect();
          return element.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
        })).toBe(true);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(unexpected).toEqual([]);
      await page.screenshot({ path: info.outputPath("hint.png") });
      await page.getByRole("button", { name: "Kết thúc", exact: true }).click();
    });
  }
}
