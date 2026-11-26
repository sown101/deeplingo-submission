import { expect, test } from "@playwright/test";

test.use({ permissions: ["microphone"], launchOptions: { args: [
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
] } });
const ITEM = "11111111-1111-4111-8111-111111111111", OTHER = "22222222-2222-4222-8222-222222222222";
type CaptureProbe = { requests: number; tracks: MediaStreamTrack[]; grant: () => Promise<void> };

for (const scenario of [{ language: "en", word: "share", width: 1280, leave: false },
  { language: "zh", word: "分享", width: 390, leave: true }]) {
  test(`cancel ${scenario.language} speaking before delayed microphone grant`, async ({ page }) => {
    await page.setViewportSize({ width: scenario.width, height: 900 });
    const unexpected: string[] = [], errors: string[] = []; let sockets = 0;
    page.on("pageerror", error => errors.push(error.name));
    await page.addInitScript(() => {
      localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
        access_token: "dummy.cancellation.token", refresh_token: "dummy-refresh", token_type: "bearer",
        expires_at: Math.floor(Date.now() / 1000) + 3600, expires_in: 3600,
        user: { id: "cancellation-ci-user", aud: "authenticated", role: "authenticated", email: "cancel@ci.invalid",
          app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
      }));
      const native = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      let grant!: () => Promise<void>;
      const probe: CaptureProbe = { requests: 0, tracks: [], grant: async () => { await grant(); } };
      (window as unknown as { captureProbe: CaptureProbe }).captureProbe = probe;
      navigator.mediaDevices.getUserMedia = (constraints) => {
        probe.requests++;
        return new Promise((resolve, reject) => {
          grant = async () => {
            try { const stream = await native(constraints); probe.tracks = stream.getTracks(); resolve(stream); }
            catch (error) { reject(error); }
          };
        });
      };
    });
    await page.route("**/*", route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (path.startsWith("/api/v1/v3/")) {
        let body: unknown;
        if (request.method() !== "GET") { unexpected.push(request.method() + " " + path); return route.abort(); }
        if (path.endsWith("/learner/me/language-profile")) body = { learning_language: scenario.language, support_language: "vi", is_complete: true };
        else if (path.endsWith("/learner/me/agent/consent")) body = { status: "granted", decided_at: "2026-10-29T10:00:00Z" };
        else if (path.endsWith("/learner/me/agent/study-requests")) body = { items: [] };
        else if (path.endsWith("/learner/me/agent/transcripts/consent")) body = { status: "revoked", decided_at: "2026-11-07T10:00:00Z", active: false };
        else if (path.endsWith("/learner/me/library/videos")) body = [];
        else if (path.endsWith("/learner/me/words")) body = { words: [], summary: null };
        else if (path.endsWith("/learner/me/lists") || path.endsWith("/learner/me/word-sets")) body = [];
      else if (path.endsWith("/learner/me/review/decks")) body = { decks: [] };
        else { unexpected.push(path); return route.abort(); }
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      }
      if (url.origin === "http://localhost:5173" || url.protocol === "blob:") return route.continue();
      unexpected.push(url.origin); return route.abort();
    });
    await page.routeWebSocket("**/learner/me/companion/realtime", socket => { sockets++; socket.close(); });
    await page.goto(`http://localhost:5173/agent?mode=voice&entry=video&scope=video&item=${ITEM}`);
    await expect.poll(() => page.evaluate(() => (window as unknown as { captureProbe: CaptureProbe }).captureProbe.requests)).toBe(1);
    if (scenario.leave) {
      await page.evaluate(() => {
        window.history.pushState({}, "", "/words/lists");
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      await expect(page.getByRole("heading", { name: "Notebooks", exact: true })).toBeVisible();
    } else {
      // Another video: the agent screen starts a new conversation and the pending capture is dropped.
      await page.evaluate((item) => {
        window.history.pushState({}, "", `/agent?mode=voice&entry=video&scope=video&item=${item}`);
        window.dispatchEvent(new PopStateEvent("popstate"));
      }, OTHER);
    }
    await page.evaluate(() => (window as unknown as { captureProbe: CaptureProbe }).captureProbe.grant());
    await expect.poll(() => page.evaluate(() => {
      const { tracks } = (window as unknown as { captureProbe: CaptureProbe }).captureProbe;
      return tracks.length > 0 && tracks.some(track => track.readyState === "ended");
    })).toBe(true);
    expect(sockets).toBe(0); expect(unexpected).toEqual([]); expect(errors).toEqual([]);
  });
}
