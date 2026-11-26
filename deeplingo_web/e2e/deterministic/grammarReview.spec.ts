import { expect, test } from "@playwright/test";

for (const language of ["en", "zh"]) {
  test(`notebook grammar ${language}: server-graded exercises, private results and the redo list`, async ({ page }) => {
    if (language === "zh") await page.setViewportSize({ width: 390, height: 844 });
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    const writes: Record<string, unknown>[] = [];
    const level = language === "en" ? "A1" : "HSK1";
    const key = `${language}.${level.toLowerCase()}.test`;
    const exercise = { id: `${key}.1`, grammar_key: key, type: "choice",
      prompt: language === "en" ? "Synthetic English question" : "测试题",
      options: ["a", "b", "c", "d"].map(id => ({ id, text: `Option ${id}` })) };
    const session = { access_token: "grammar-dummy-jwt.header.token", token_type: "bearer", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, refresh_token: "grammar-dummy-refresh",
      user: { id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", aud: "authenticated", role: "authenticated",
        email: "grammar@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" } };
    await page.addInitScript(value => { if (location.origin === "http://localhost:5173")
      localStorage.setItem("sb-ci-dummy-auth-token", value); }, JSON.stringify(session));
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      const json = (body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      if (url.pathname.startsWith("/api/v1/v3/")) {
        const path = url.pathname.replace("/api/v1/v3", "");
        if (path === "/learner/me/language-profile") return json({ learning_language: language, support_language: "vi", is_complete: true });
        if (path === "/learner/me/lists") return json([]);
        if (path === "/learner/me/words") return json({ words: [], summary: null });
        if (path === "/learner/me/review/decks") return json({ decks: [] });
        if (path === `/learner/me/grammar/${language}`) return json({ language_code: language, support_language: "vi", levels: [level],
          level, topics: [{ key: "test", title: "Test topic" }],
          points: [{ key, title: "Test point", topic_key: "test", lesson: null, exercise_count: 1, attempts: writes.length,
            correct_count: writes.length, incorrect_count: 0, lesson_learned_at: null, last_correct_at: null }],
          redo: writes.length ? [] : [{ request_id: "r-1", grammar_key: key, title: "Test point", level, reason: "Said it wrong",
            created_at: "2026-11-14T00:00:00Z" }] });
        if (path === `/learner/me/grammar/${language}/exercises`) {
          expect(url.searchParams.get("grammar_key")).toBe(key);
          return json({ language_code: language, grammar_key: key, exercises: [exercise] });
        }
        if (route.request().method() === "POST" && path === "/learner/me/grammar/answers") {
          const body = route.request().postDataJSON();
          writes.push(body);
          expect(Object.keys(body).sort()).toEqual(["client_event_id", "exercise_id", "language_code", "option_id"]);
          return json({ client_event_id: body.client_event_id, exercise_id: body.exercise_id, grammar_key: key, correct: true,
            correct_option_id: "a", explanation: "Stored grammar explanation", redo_closed: 1, duplicate: false });
        }
        return route.fulfill({ status: 404, body: "{}", contentType: "application/json" });
      }
      return url.origin === "http://localhost:5173" ? route.continue() : route.abort();
    });
    await page.goto("/words/lists?tab=grammar");
    await expect(page.getByRole("heading", { name: "Test topic" })).toBeVisible();
    await expect(page.getByText("Said it wrong")).toBeVisible();
    expect(writes).toHaveLength(0);
    await page.getByRole("button", { name: "Redo", exact: true }).click();
    await page.getByLabel("Option a").check();
    await page.getByRole("button", { name: "Check" }).click();
    await expect(page.getByText("Stored grammar explanation")).toBeVisible();
    await expect(page.getByText("Removed from your redo list.")).toBeVisible();
    await page.getByRole("button", { name: "Next question" }).click();
    await expect(page.getByText("Practice round complete.")).toBeVisible();
    await expect(page).toHaveURL(/\/words\/lists\?tab=grammar$/);
    expect(writes).toHaveLength(1); expect(errors).toEqual([]);
  });
}
