import { expect, test } from "@playwright/test";
import { browserLaunchOptions } from "../../scripts/m1_runtime_helpers.mjs";

test.use({ launchOptions: browserLaunchOptions() });
const API = "/api/v1/v3";

// One review of a deck from the link to the summary, in one language each: the server builds the exercises from the
// chosen types, the client sends only the learner's input, every answer carries the same pass id and its own event id.
const SCENARIOS = [
  {
    language: "en",
    link: "choice%2Cmatch%2Corder",
    types: "choice,listening,match,order",
    cards: [
      { concept_id: "c-1", text: "leave", reading: null, is_new: false, due_at: "2026-11-01T00:00:00Z",
        exercise: { type: "choice", prompt: { text: "leave", reading: null, sentence: "I have to leave now.", options: ["rời đi", "cái bàn", "dòng sông"] } } },
      { concept_id: "c-2", text: "table", reading: null, is_new: true, due_at: null,
        exercise: { type: "listening", prompt: { options: ["table", "river", "garden"] } } },
      { concept_id: "c-3", text: "river", reading: null, is_new: true, due_at: null,
        exercise: { type: "match", prompt: { text: "river", reading: null, meaning: "dòng sông" } } },
      { concept_id: "c-4", text: "garden", reading: null, is_new: true, due_at: null,
        exercise: { type: "match", prompt: { text: "garden", reading: null, meaning: "khu vườn" } } },
      { concept_id: "c-5", text: "book", reading: null, is_new: true, due_at: null,
        exercise: { type: "order", prompt: { kind: "sentence", parts: ["book", "is", "The", "here"], meaning: "quyển sách" } } },
    ],
    steps: [
      { kind: "click", parts: ["rời đi"] },
      { kind: "click", parts: ["table"] },
      { kind: "match", parts: ["river", "dòng sông", "garden", "khu vườn"] },
      { kind: "order", parts: ["The", "book", "is", "here"] },
    ],
    answers: [
      ["c-1", "choice", { option: "rời đi" }], ["c-2", "listening", { option: "table" }], ["c-3", "match", { option: "dòng sông" }],
      ["c-4", "match", { option: "khu vườn" }], ["c-5", "order", { text: "The book is here" }],
    ],
  },
  {
    language: "zh",
    link: "choice%2Corder%2Cwrite",
    types: "choice,listening,order,writing",
    cards: [
      { concept_id: "z-1", text: "你好", reading: "nǐ hǎo", is_new: false, due_at: "2026-11-01T00:00:00Z",
        exercise: { type: "choice", prompt: { text: "你好", reading: "nǐ hǎo", sentence: null, options: ["xin chào", "cảm ơn", "tạm biệt"] } } },
      { concept_id: "z-2", text: "学习", reading: "xué xí", is_new: true, due_at: null,
        exercise: { type: "order", prompt: { kind: "characters", parts: ["习", "学"], meaning: "học tập" } } },
      { concept_id: "z-3", text: "老师", reading: "lǎo shī", is_new: true, due_at: null,
        exercise: { type: "writing", prompt: { script: "strokes", characters: "老师", reading: "lǎo shī", meaning: "giáo viên" } } },
    ],
    steps: [
      { kind: "click", parts: ["xin chào"] },
      { kind: "order", parts: ["学", "习"] },
      { kind: "type", parts: ["老师"] },
    ],
    answers: [["z-1", "choice", { option: "xin chào" }], ["z-2", "order", { text: "学习" }], ["z-3", "writing", { text: "老师" }]],
  },
] as const;

for (const scenario of SCENARIOS) {
  test(`a full review runs every chosen type through one screen: ${scenario.language}`, async ({ page }) => {
    const answers: Record<string, unknown>[] = [], unexpected: string[] = [], errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: "review.dummy.jwt", token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: "review-ci-user", aud: "authenticated", role: "authenticated", email: "review@ci.invalid",
        app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    })));
    await page.route("**/*", route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (path.startsWith(API + "/")) {
        expect(request.headers().authorization).toBe("Bearer review.dummy.jwt");
        let body: unknown;
        if (path.endsWith("/language-profile")) {
          body = { learning_language: scenario.language, support_language: "vi", is_complete: true };
        } else if (path === `${API}/learner/me/review/${scenario.language}/due`) {
          expect(url.searchParams.get("types")).toBe(scenario.types);
          body = { language_code: scenario.language, due_count: 1, new_count: scenario.cards.length - 1, cards: scenario.cards };
        } else if (path === `${API}/learner/me/review/answers` && request.method() === "POST") {
          const sent = request.postDataJSON() as Record<string, unknown>;
          for (const field of ["correct", "grade", "score", "user_id", "expected"]) expect(sent).not.toHaveProperty(field);
          answers.push(sent);
          const card = scenario.cards.find(item => item.concept_id === sent.concept_id)!;
          body = { client_event_id: sent.client_event_id, concept_id: sent.concept_id, exercise_type: sent.exercise_type,
            outcome: "correct", correct: true, grade: "good", scheduled: sent.exercise_type !== "writing",
            next_review_at: "2026-11-20T00:00:00Z", expected: card.text, duplicate: false };
        } else {
          unexpected.push(`${request.method()} ${path}`);
          return route.abort();
        }
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      }
      if (url.origin === "http://localhost:5173") return route.continue();
      return route.abort();
    });

    await page.goto(`http://localhost:5173/review/${scenario.language}?types=${scenario.link}&images=0`);
    for (const [index, step] of scenario.steps.entries()) {
      await expect(page.locator(".st-progress")).toContainText(`${index + 1}/${scenario.steps.length}`);
      if (step.kind === "click") await page.locator(".st-ans-col").getByRole("button", { name: step.parts[0], exact: true }).click();
      if (step.kind === "match") {
        for (let pair = 0; pair < step.parts.length; pair += 2) {
          await page.getByRole("group", { name: "Words" }).getByRole("button", { name: step.parts[pair] }).click();
          await page.getByRole("group", { name: "Meanings" }).getByRole("button", { name: step.parts[pair + 1] }).click();
        }
      }
      if (step.kind === "order") {
        for (const part of step.parts) await page.getByTestId("order-bank").getByRole("button", { name: part, exact: true }).click();
        await page.getByRole("button", { name: "Check", exact: true }).click();
      }
      if (step.kind === "type") {
        await page.getByRole("textbox", { name: "Type the word" }).fill(step.parts[0]);
        await page.getByRole("button", { name: "Check", exact: true }).click();
      }
      if (step.kind !== "match") await expect(page.getByText("Correct", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Continue", exact: true }).click();
    }
    await expect(page.getByText("You finished this review.")).toBeVisible();
    await expect(page.locator(".st-summary-score")).toHaveText(`${scenario.answers.length}/${scenario.answers.length}`);

    expect(answers.map(answer => [answer.concept_id, answer.exercise_type, answer.answer])).toEqual(scenario.answers);
    expect(new Set(answers.map(answer => answer.pass_id)).size).toBe(1);
    expect(new Set(answers.map(answer => answer.client_event_id)).size).toBe(answers.length);
    expect(answers.every(answer => answer.language_code === scenario.language)).toBe(true);
    expect(unexpected).toEqual([]);
    expect(errors).toEqual([]);
  });
}
