import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  test(`clean word screens and a review graded in place, ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const writes: string[] = [], unexpected: string[] = [];
    await page.addInitScript(() => localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: "review-dummy.header.token", token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: "review-ci-user", aud: "authenticated", role: "authenticated",
        email: "review@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    })));
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      if (url.pathname.startsWith("/api/")) {
        if (route.request().method() !== "GET") { writes.push(url.pathname); return route.abort(); }
        if (url.pathname.endsWith("/language-profile")) return json({ learning_language: "en", support_language: "vi", is_complete: true, declared_level: "A2" });
        if (url.pathname.endsWith("/lists")) return json([]);
        if (url.pathname.endsWith("/words")) return json({ words: ["reservation", "itinerary"].map((text, index) => ({
          concept_id: `33333333-3333-4333-8333-${String(index + 1).padStart(12, "0")}`, language_code: "en", text,
          kind: "word", gloss: index ? "A plan for a journey." : "An arrangement to keep a place.", list: "saved", saved: true,
          save_source: "manual", explicit: true, status: "active", added_at: `2026-10-${31 - index}T00:00:00Z`, next_review_at: null,
        })), summary: null });
        if (url.pathname.endsWith("/examples")) {
          expect(url.searchParams.get("read_only")).toBe("true"); return json({ examples: [] });
        }
        unexpected.push(url.pathname); return route.abort();
      }
      if (url.origin === "http://localhost:5173") return route.continue();
      unexpected.push(url.origin); return route.abort();
    });
    await page.goto("/words?level=0");
    await expect(page.getByText("reservation", { exact: true })).toBeVisible();
    const main = page.getByRole("main");
    for (const name of ["Speak with your agent", "Notebooks", "Learning progress"]) {
      await expect(main.getByRole("link", { name, exact: true })).toHaveCount(0);
    }
    await expect(page.getByText("Saved words are ready for review right away.", { exact: false })).toHaveCount(0);
    // The review grades in place: the question stays, the chosen option and the right one are marked, and Continue is
    // not covered by the Tata bar.
    let answers = 0;
    await page.route("**/learner/me/review/en/due**", route => route.fulfill({ contentType: "application/json", body: JSON.stringify({
      language_code: "en", due_count: 1, new_count: 0, cards: [{ concept_id: "33333333-3333-4333-8333-000000000001", text: "reservation",
        reading: null, is_new: false, due_at: "2026-11-01T00:00:00Z", exercise: { type: "choice", prompt: { text: "reservation", reading: null,
          sentence: null, options: ["A booking", "A journey", "A ticket"] } } }] }) }));
    await page.route("**/learner/me/review/answers", route => {
      const body = route.request().postDataJSON();
      expect(Object.keys(body).sort()).toEqual(["answer", "client_event_id", "concept_id", "exercise_type", "hint_used", "language_code", "pass_id", "response_ms"]);
      expect(body.answer).toEqual({ option: "A journey" });
      answers++;
      return route.fulfill({ contentType: "application/json", body: JSON.stringify({ client_event_id: body.client_event_id, concept_id: body.concept_id,
        exercise_type: "choice", outcome: "incorrect", correct: false, grade: "again", scheduled: true, next_review_at: "2026-11-15T00:00:00Z",
        expected: "A booking", duplicate: false }) });
    });
    await page.goto("/review/en?types=choice&images=0");
    await expect(page.getByText("reservation", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "A journey", exact: true }).click();
    await expect(page.locator(".st-fb.bad")).toContainText("Not quite · Answer: A booking");
    await expect(page.getByText("reservation", { exact: true })).toBeVisible();
    await expect(page.locator(".st-ans.bad")).toHaveText("A journey");
    await expect(page.locator(".st-ans.good")).toHaveText("A booking");
    await expect(page.getByRole("button", { name: "A journey", exact: true })).toBeDisabled();
    expect(answers).toBe(1);
    const next = page.getByRole("button", { name: "Continue", exact: true });
    const primaryColor = await next.evaluate(element => {
      const probe = document.createElement("span"); probe.style.color = "var(--blue-strong)"; element.append(probe);
      const color = getComputedStyle(probe).color; probe.remove(); return color;
    });
    await expect(next).toHaveCSS("background-color", primaryColor);
    // Review screens stand alone: the Tata bar is not shown, so nothing covers Continue.
    await expect(page.locator(".agent-launcher")).toHaveCount(0);
    await expect(next).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("graded-in-place.png") });
    await next.click();
    await expect(page.getByText("You finished this review.")).toBeVisible();
    await expect(main.getByRole("link", { name: "Home", exact: true })).toHaveCount(0);
    expect(writes).toEqual([]); expect(unexpected).toEqual([]);  });
}
