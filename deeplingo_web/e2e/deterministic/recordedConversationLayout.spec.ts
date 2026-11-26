import { expect, test } from "@playwright/test";

test.use({ permissions: ["microphone"], launchOptions: { args: [
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
] } });

for (const [width, height] of [[390, 844], [1280, 900], [1920, 1080]]) {
  test(`recorded fallback keeps its transcript and controls separate at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    const unexpected: string[] = [], errors: string[] = [];
    let turns = 0, finishes = 0;
    page.on("pageerror", error => errors.push(error.name));
    await page.addInitScript(() => {
      localStorage.setItem("deeplingo.ui_language", "vi");
      localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
        access_token: "recorded-dummy.header.token", token_type: "bearer", refresh_token: "dummy-refresh",
        expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
        user: { id: "recorded-ci-user", aud: "authenticated", role: "authenticated", email: "recorded@ci.invalid",
          app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
      }));
      const probe = window as unknown as { recordedPcmSeconds: number };
      probe.recordedPcmSeconds = 0;
      const NativeWorklet = window.AudioWorkletNode;
      window.AudioWorkletNode = class extends NativeWorklet {
        constructor(context: BaseAudioContext, name: string, options?: AudioWorkletNodeOptions) {
          super(context, name, options);
          probe.recordedPcmSeconds = 0;
          this.port.addEventListener("message", (event: MessageEvent<Float32Array>) => {
            probe.recordedPcmSeconds += event.data.length / context.sampleRate;
          });
          this.port.start();
        }
      };
    });
    const turn = () => ({
      session_ticket: `signed.ticket-${turns}`, expires_at: "2099-01-01T00:00:00Z",
      turn: turns, max_turns: 30, finished: false, language_code: "en", support_language_code: "vi",
      entry: "home", library_item_id: null, topic: "School",
      learner_transcript: turns ? `I read a book at school. This is my answer ${turns}.` : null,
      reply: `Tell me about a book you enjoyed reading at school. What did you like about it? Question ${turns}.`,
      reply_support: "Hãy kể về một cuốn sách bạn thích đọc ở trường. Bạn thích điều gì ở nó?",
      hints: { question: "Which book did you read?", items: [], frame: null, model_sentence: null },
      correction: null, used_items: [], next: "continue", audio: null, audio_status: "unavailable",
      looked_up: [], follow_ups: [], practice_suggestion: null,
    });
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      if (url.pathname.endsWith("/learner/me/language-profile")) return json({ learning_language: "en", support_language: "vi", is_complete: true });
      if (url.pathname.endsWith("/learner/me/agent/consent")) return json({ status: "granted", decided_at: "2026-11-06T00:00:00Z" });
      if (url.pathname.endsWith("/learner/me/agent/study-requests")) return json({ items: [] });
      if (url.pathname.endsWith("/learner/me/agent/transcripts/consent")) return json({ status: "revoked", decided_at: "2026-11-07T00:00:00Z", active: false });
      if (url.pathname.endsWith("/learner/me/words")) return json({ words: [], summary: null });
      if (url.pathname.endsWith("/learner/me/lists")) return json([]);
      if (url.pathname.endsWith("/learner/me/companion/sessions")) return json(turn());
      if (url.pathname.endsWith("/learner/me/companion/turns/stream")) {
        expect(route.request().headers()["content-type"]).toContain("multipart/form-data");
        turns++;
        return route.fulfill({ contentType: "application/x-ndjson",
          body: JSON.stringify({ type: "turn", turn: turn() }) + "\n" + JSON.stringify({ type: "done" }) + "\n" });
      }
      if (url.pathname.endsWith("/learner/me/companion/finish")) { finishes++; return json({}); }
      if (url.origin === "http://localhost:5173" && !url.pathname.startsWith("/api/")) return route.continue();
      unexpected.push(url.pathname); return route.abort();
    });
    // Live voice is unavailable: the same agent screen continues as recorded or typed turns.
    await page.routeWebSocket("**/learner/me/companion/realtime", socket => socket.onMessage(raw => {
      if (typeof raw === "string" && JSON.parse(raw).type === "start") {
        socket.send(JSON.stringify({ type: "error", code: "realtime_unavailable", message: "unavailable" }));
        void socket.close({ code: 1011 });
      }
    }));
    await page.goto("/agent?entry=home");
    await page.getByRole("button", { name: "Gõ chữ hoặc ghi âm từng lượt", exact: true }).click();
    const speak = page.getByRole("button", { name: "Chạm để nói", exact: true });
    await expect(speak).toBeVisible();
    const thread = page.locator(".companion-thread"), stage = page.locator(".companion-stage");
    async function checkLayout() {
      const layoutBox = (await page.locator(".companion-layout").boundingBox())!;
      const conversationBox = (await page.locator(".companion-conversation").boundingBox())!;
      const threadBox = (await thread.boundingBox())!, stageBox = (await stage.boundingBox())!;
      expect(layoutBox.width).toBeGreaterThanOrEqual(conversationBox.width - 2);
      expect(threadBox.width).toBeGreaterThanOrEqual(layoutBox.width - 2);
      expect(threadBox.y + threadBox.height).toBeLessThanOrEqual(stageBox.y + 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      for (const button of await page.locator(".companion-controls button:visible").all()) {
        expect(await button.evaluate(element => {
          const box = element.getBoundingClientRect();
          return box.top >= 0 && box.bottom <= innerHeight
            && element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
        })).toBe(true);
      }
    }
    await checkLayout();
    await page.screenshot({ path: info.outputPath("recorded-start.png") });
    for (let index = 0; index < 6; index++) {
      await speak.click();
      const send = page.getByRole("button", { name: /^Chạm để gửi/ });
      await expect(send).toBeVisible();
      await expect.poll(() => page.evaluate(() =>
        (window as unknown as { recordedPcmSeconds: number }).recordedPcmSeconds
      )).toBeGreaterThan(.5); // Wait for captured PCM, not wall time on a busy worker.
      await send.click();
      await expect(speak).toBeVisible();
      await expect.poll(() => turns).toBe(index + 1);
    }
    await expect(page.locator(".bubble.learner")).toHaveCount(6);
    await expect.poll(() => page.locator(".bubble.companion").last().evaluate(element => {
      const box = element.getBoundingClientRect();
      const thread = element.closest(".companion-thread")!.getBoundingClientRect();
      return box.top >= thread.top && box.bottom <= thread.bottom;
    })).toBe(true);
    await page.getByRole("button", { name: "Cần gợi ý?", exact: true }).click();
    await expect(page.getByText("Which book did you read?", { exact: true })).toBeVisible();
    await thread.evaluate(element => { element.scrollTop = element.scrollHeight; });
    await checkLayout();
    expect(await thread.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
    await page.screenshot({ path: info.outputPath("recorded-history.png") });
    await page.getByRole("button", { name: "Kết thúc trò chuyện", exact: true }).click();
    await expect(page.getByRole("button", { name: "Bắt đầu cuộc trò chuyện mới", exact: true })).toBeVisible();
    expect(finishes).toBe(1);
    expect(unexpected).toEqual([]);
    expect(errors).toEqual([]);
  });
}
