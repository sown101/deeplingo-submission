import { expect, test } from "@playwright/test";

// Synthetic Auth/API/WebSocket only; browser microphone and PCM playback use Chromium's fake device.
test.use({ permissions: ["microphone"], launchOptions: { args: [
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
] } });

const ITEM = "22222222-2222-4222-8222-222222222222";
const JWT = "l2-dummy.header.token";

for (const scenario of [{ language: "en", word: "airport", width: 1280, entry: "home" },
  { language: "zh", word: "机场", width: 390, entry: "video" }]) {
  test(`L2 ${scenario.language}: stored consent, PCM and session cleanup`, async ({ page }, info) => {
    await page.setViewportSize({ width: scenario.width, height: 900 });
    const unexpected: string[] = [], errors: string[] = [];
    let microphoneFrames = 0;
    page.on("pageerror", (error) => errors.push(error.name));
    await page.addInitScript((token) => localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: token, token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
      refresh_token: "dummy-refresh", user: { id: "l2-ci-user", aud: "authenticated", role: "authenticated",
        email: "l2@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    })), JWT);
    await page.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith("/api/v1/v3/")) {
        expect(route.request().headers().authorization).toBe(`Bearer ${JWT}`);
        let body: unknown;
        if (url.pathname.endsWith("/learner/me/language-profile")) body = {
          learning_language: scenario.language, support_language: "vi", is_complete: true,
        };
        else if (url.pathname.endsWith("/learner/me/agent/consent")) body = { status: "granted", decided_at: "2026-10-29T10:00:00Z" };
        else if (url.pathname.endsWith("/learner/me/agent/study-requests")) body = { items: [] };
        else if (url.pathname.endsWith("/learner/me/agent/transcripts/consent")) body = { status: "revoked", decided_at: "2026-11-07T10:00:00Z", active: false };
        else if (url.pathname.endsWith("/learner/me/lists")) body = [];
        else if (url.pathname.endsWith("/learner/me/words")) body = { words: [{ concept_id: "33333333-3333-4333-8333-333333333333", language_code: scenario.language, text: scenario.word, kind: "word", list: "saved", saved: true, status: "active", rung: 0 }], summary: null };
        else { unexpected.push(url.pathname); return route.abort(); }
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      }
      if (url.origin === "http://localhost:5173" || url.protocol === "blob:") return route.continue();
      unexpected.push(url.origin); return route.abort();
    });
    await page.routeWebSocket("**/learner/me/companion/realtime", (socket) => {
      expect(socket.url()).not.toContain(JWT);
      socket.onMessage((raw) => {
        if (typeof raw !== "string") {
          microphoneFrames++;
          expect(raw.byteLength).toBeGreaterThan(0);
          expect(raw.byteLength).toBeLessThanOrEqual(32000);
          return;
        }
        const message = JSON.parse(raw);
        if (message.type === "auth") expect(message.token).toBe(JWT);
        else if (message.type === "start") {
          expect(message.target_concept_ids).toBeUndefined();
          expect(message.analyze_session).toBeUndefined();
          expect(message.entry).toBe(scenario.entry);
          if (scenario.entry === "video") expect(message.library_item_id).toBe(ITEM);
          socket.send(JSON.stringify({ type: "ready", max_seconds: 60, language_code: scenario.language, topic: "Travel" }));
          socket.send(JSON.stringify({ type: "audio_format", sample_rate: 24000 }));
          socket.send(Buffer.alloc(4800));
          socket.send(JSON.stringify({ type: "transcript", role: "companion", text: scenario.language === "zh" ? "你去过机场吗？" : "Have you been to an airport?" }));
          socket.send(JSON.stringify({ type: "turn_complete" }));
        } else if (message.type === "end") {
          socket.send(JSON.stringify({ type: "ended", reason: "learner_ended", remembered: false, follow_ups: [] }));
          socket.close({ code: 1000 });
        } else unexpected.push("WebSocket:" + message.type);
      });
    });
    await page.goto(`/agent?mode=voice&entry=${scenario.entry}${scenario.entry === "video" ? "&item=" + ITEM : ""}`);
    await page.screenshot({ path: info.outputPath("voice-start.png"), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(page.getByLabel("Transcript")).toContainText(scenario.language === "zh" ? "机场" : "airport");
    await expect.poll(() => microphoneFrames).toBeGreaterThan(0);
    await page.getByRole("button", { name: "End", exact: true }).click();
    await expect(page.getByText("You ended the conversation.", { exact: true })).toBeVisible();
    const framesAfterEnd = microphoneFrames;
    await page.waitForTimeout(350);
    expect(microphoneFrames).toBe(framesAfterEnd);
    await expect(page.getByRole("button", { name: "Start again", exact: true })).toBeVisible();
    expect(unexpected).toEqual([]); expect(errors).toEqual([]);
  });
}
