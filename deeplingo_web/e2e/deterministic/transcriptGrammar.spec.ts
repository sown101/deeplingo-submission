import { expect, test } from "@playwright/test";
import { browserLaunchOptions } from "../../scripts/m1_runtime_helpers.mjs";

test.use({ launchOptions: browserLaunchOptions() });
const ITEM = "11111111-1111-4111-8111-111111111111", SEG = "22222222-2222-4222-8222-222222222222";
const OCC = "33333333-3333-4333-8333-333333333333", API = "/api/v1/v3";
for (const scenario of [
  { language: "en", sentence: "I am happy.", marked: "am", start: 2, end: 4, plain: "happy", plainStart: 5, plainEnd: 10 },
  { language: "zh", sentence: "我是学生。", marked: "是", start: 1, end: 2, plain: "学", plainStart: 2, plainEnd: 3 },
]) {
  test(`transcript grammar is explicit and does not record a lookup: ${scenario.language}`, async ({ page }) => {
    if (scenario.language === "zh") await page.setViewportSize({ width: 390, height: 844 });
    const requests: Record<string, unknown>[] = [], unexpected: string[] = [], errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => { if (location.origin !== "http://localhost:5173") return;
      localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: "grammar.dummy.jwt", token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: "grammar-ci-user", aud: "authenticated", role: "authenticated", email: "grammar@ci.invalid",
        app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
      }));
    });
    await page.route("**/*", route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (path.startsWith(API + "/")) {
        expect(request.headers().authorization).toBe("Bearer grammar.dummy.jwt");
        let body: unknown;
        if (path.endsWith("/language-profile")) {
          body = { learning_language: scenario.language, support_language: "vi", is_complete: true };
        } else if (path.endsWith("/playback")) {
          body = { library_item_id: ITEM, video_id: ITEM, provider: "youtube", external_video_id: "jNQXAC9IVRw",
            title: "Grammar video", language_code: scenario.language, duration_ms: 3000 };
        } else if (path.endsWith("/transcript")) {
          body = { library_item_id: ITEM, language_code: scenario.language, translation_language_code: "vi", segments: [{
            segment_id: SEG, sequence: 1, text: scenario.sentence, start_ms: 0, end_ms: 3000,
            translation: null, romanizations: [], learning_objects: [{ learning_object_id: OCC,
              start_codepoint: scenario.start, end_codepoint: scenario.end, grammar_key: `${scenario.language}.example` }],
          }] };
        } else if (path.endsWith("/translations")) {
          body = { status: "not_needed", language_code: null, translated: 0 };
        } else if (path.endsWith("/learner/me/agent/consent")) {
          body = { status: "granted", decided_at: "2026-10-29T10:00:00Z" };
        } else if (path.endsWith("/parts")) {
          // AI study parts are covered by aiStudyParts.spec; unavailable here.
          return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
        } else if (path.endsWith("/workspace") || path.endsWith("/workspace/position")) {
          body = { library_item_id: ITEM, position_ms: null, region: null };
        } else if (path.endsWith("/grammar-explanations") && request.method() === "POST") {
          const submitted = request.postDataJSON() as Record<string, unknown>;
          expect(Object.keys(submitted).sort()).toEqual(["end_codepoint", "scope", "segment_id", "start_codepoint"]);
          expect(submitted.segment_id).toBe(SEG);
          requests.push(submitted);
          const whole = submitted.scope === "sentence";
          const known = whole || (submitted.start_codepoint === scenario.start && submitted.end_codepoint === scenario.end);
          const source = whole ? scenario.sentence
            : [...scenario.sentence].slice(Number(submitted.start_codepoint), Number(submitted.end_codepoint)).join("");
          body = { segment_id: SEG, scope: submitted.scope, source_text: source, support_language_code: "vi",
            source: known ? "curriculum_draft" : "ai_unverified", grammar_keys: [], explanation: {
              sentence_structure: { title: "Cấu trúc câu", text: "Chủ ngữ + vị ngữ." },
              grammar: { title: "Ngữ pháp", text: "Giải thích ngắn từ nguồn đã chọn." },
              important_words: { title: "Từ và cụm quan trọng", text: "Các từ có trong câu." },
            } };
        } else {
          unexpected.push(`${request.method()} ${path}`);
          return route.abort();
        }
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      }
      if (url.origin === "http://localhost:5173") return route.continue();
      return route.abort();
    });
    await page.goto(`http://localhost:5173/library/videos/${ITEM}/watch`);
    const transcript = page.getByRole("region", { name: "Transcript", exact: true });
    await expect(transcript).toBeVisible();
    expect(requests).toEqual([]);
    await transcript.getByRole("button", { name: scenario.marked, exact: true }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Prepared content, not yet approved")).toBeVisible();
    await expect(dialog.getByRole("heading", { level: 3 })).toHaveText(["Cấu trúc câu", "Ngữ pháp", "Từ và cụm quan trọng"]);
    await dialog.getByRole("button", { name: "Close grammar explanation" }).click();

    await expect(page.getByLabel("When selecting text")).toHaveCount(0);
    await transcript.getByText(scenario.plain, { exact: true }).evaluate(element => {
      const range = document.createRange(); range.selectNodeContents(element.firstChild!);
      window.getSelection()?.removeAllRanges(); window.getSelection()?.addRange(range);
    });
    await transcript.getByRole("button", { name: "Analyse sentence", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("AI explanation, unverified")).toBeVisible();
    await dialog.getByRole("button", { name: "Analyse the whole sentence" }).click();
    await expect(dialog.getByText(scenario.sentence, { exact: true })).toBeVisible();
    expect(requests).toEqual([
      { segment_id: SEG, start_codepoint: scenario.start, end_codepoint: scenario.end, scope: "selection" },
      { segment_id: SEG, start_codepoint: scenario.plainStart, end_codepoint: scenario.plainEnd, scope: "selection" },
      { segment_id: SEG, start_codepoint: scenario.plainStart, end_codepoint: scenario.plainEnd, scope: "sentence" },
    ]);
    expect(unexpected).toEqual([]);
    expect(errors).toEqual([]);
  });
}
