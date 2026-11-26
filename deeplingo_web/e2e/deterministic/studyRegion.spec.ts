import { expect, test } from "@playwright/test";
import { browserLaunchOptions } from "../../scripts/m1_runtime_helpers.mjs";

// One full study region (PRD 8.10, TARGET_DESIGN section 6): watch with the meaning under each line, look a phrase up and save
// it, practise Dictation, Shadowing and Questions, then read the result card. All server responses are synthetic: the
// mock server keeps the practice it receives and sums it for the result card, as the real server does from its log.
test.use({ launchOptions: browserLaunchOptions() });

const API = "/api/v1/v3/learner/me";
const ITEM = "11111111-1111-4111-8111-111111111111";
const TRACK = "22222222-2222-4222-8222-222222222222";
const QUESTION = "66666666-7777-8888-9999-aaaaaaaaaaaa";
const CONCEPT = "53a24597-033f-461e-95f7-4c8e8ad02ed5";
const seg = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

const SCENARIOS = [
  { language: "en", lines: ["So I ended up taking a taxi.", "It was a long ride.", "Then we arrived."], answer: "So I ended up taking a taxi",
    phrase: { start: 5, end: 13, text: "ended up" }, spaced: true, wordFrom: 2, wordTo: 3 },
  { language: "zh", lines: ["我想订一个房间。", "我们坐出租车去。", "然后我们到了。"], answer: "我想订一个房间",
    phrase: { start: 2, end: 4, text: "订一" }, spaced: false, wordFrom: 2, wordTo: 3 },
] as const;

for (const scenario of SCENARIOS) {
  test(`one study region from watching to the result card: ${scenario.language}`, async ({ page }) => {
    const region = { start: seg(1), end: seg(3) };
    const regionId = `${region.start}_${region.end}`;
    const seen = { translations: 0, saved: [] as Record<string, unknown>[], lookups: [] as Record<string, unknown>[],
      dictation: [] as Record<string, unknown>[], shadowing: [] as string[], answers: 0 };
    let translated = false;
    let savedRegion: unknown = null;
    const unexpected: string[] = [], errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      if (location.origin !== "http://localhost:5173") return;
      localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({ access_token: "region.dummy.jwt", token_type: "bearer",
        refresh_token: "dummy-refresh", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
        user: { id: "region-ci-user", aud: "authenticated", role: "authenticated", email: "region@ci.invalid",
          app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" } }));
    });

    const rows = () => scenario.lines.map((text, index) => ({
      segment_id: seg(index + 1), sequence: index + 1, text, start_ms: index * 4000, end_ms: (index + 1) * 4000,
      translation: translated ? { language_code: "vi", text: `Nghĩa câu ${index + 1}` } : null, romanizations: [], learning_objects: [],
    }));
    await page.route("**/*", (route) => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
      const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      if (!path.startsWith("/api/")) return url.origin === "http://localhost:5173" ? route.continue() : route.abort();
      const own = path.startsWith(`${API}/library/videos/${ITEM}/`) ? path.slice(`${API}/library/videos/${ITEM}`.length) : null;
      if (path === `${API}/language-profile`) return json({ learning_language: scenario.language, support_language: "vi", is_complete: true });
      if (path === `${API}/agent/consent`) return json({ status: "granted", decided_at: "2026-10-29T10:00:00Z" });
      if (path === `${API}/lists`) return json([]);
      if (path === `${API}/words` && method === "POST") {
        seen.saved.push(request.postDataJSON() as Record<string, unknown>);
        return json({ concept_id: CONCEPT, language_code: scenario.language, text: scenario.phrase.text, kind: "phrase", gloss: "nghĩa",
          list: "saved", saved: true, save_source: "lookup" });
      }
      if (path === `${API}/words/${CONCEPT}/examples`) return json({ examples: [] });
      if (own === "/playback") return json({ library_item_id: ITEM, video_id: ITEM, provider: "youtube", external_video_id: "jNQXAC9IVRw",
        title: "Study region video", language_code: scenario.language, duration_ms: 12000 });
      if (own === "/transcript") return json({ library_item_id: ITEM, language_code: scenario.language, translation_language_code: "vi", segments: rows() });
      if (own === "/translations") { seen.translations += 1; translated = true; return json({ status: "ready", language_code: "vi", translated: 3 }); }
      if (own === "/parts") return json({ transcript_id: TRACK, source: "ai", parts: [{ start_segment_id: region.start, end_segment_id: region.end,
        start_ms: 0, end_ms: 12000, segment_count: 3, title: "Cả đoạn" }] });
      if (own === "/workspace/region" && method === "PUT") {
        savedRegion = { transcript_id: TRACK, start_segment_id: region.start, end_segment_id: region.end, start_ms: 0, end_ms: 12000,
          segment_count: 3, preparation: { status: "ready", usable_count: 1, retryable: false, reset_at: null, questions_status: "ready" } };
        return json({ library_item_id: ITEM, position_ms: null, region: savedRegion });
      }
      if (own === "/workspace" || own === "/workspace/position") return json({ library_item_id: ITEM, position_ms: null, region: savedRegion });
      if (own === "/lookup") {
        const body = request.postDataJSON() as { segment_id: string; start_codepoint: number; end_codepoint: number };
        return json({ segment_id: body.segment_id, selection_start: body.start_codepoint, selection_end: body.end_codepoint,
          unit_start: body.start_codepoint, unit_end: body.end_codepoint, unit_text: scenario.phrase.text, unit_kind: "phrase",
          selection_is_part: false, headword: scenario.phrase.text, reading: null, part_of_speech: null, dictionary_gloss: null,
          sense_id: "sense-1", meaning: "kết thúc ở", note: null, pattern: [], pattern_explanation: null, examples: [],
          context_before: null, context_after: null, meaning_provenance: "translated_from_sense", level: null, source: null });
      }
      if (own === "/practice-events/lookup") { seen.lookups.push(request.postDataJSON() as Record<string, unknown>); return json({ id: "x", kind: "word_lookup", status: "created" }); }
      if (own === "/practice-events/dictation") {
        seen.dictation.push(request.postDataJSON() as Record<string, unknown>);
        return json({ id: "x", kind: "dictation_checked", status: "created", total: 3, correct: 3, missed: [] });
      }
      if (own === "/shadowing/assessments") {
        seen.shadowing.push(request.postData() ?? "");
        return json({ library_item_id: ITEM, segment_id: seg(1), language_code: scenario.language, reference_text: scenario.lines[0],
          recognized_text: scenario.lines[0], band: "good", scores: { pronunciation: 80, accuracy: 80, fluency: 80, completeness: 80, prosody: null },
          words: [], attempt_duration_ms: 1500, reference_duration_ms: 4000, spoken_duration_ms: 1200 });
      }
      if (own === "/region-questions") return json({ status: "ready", questions: [{ id: QUESTION, position: 1, question: "Câu hỏi?", options: ["A", "B", "C", "D"] }] });
      if (own === `/region-questions/${QUESTION}/answer`) {
        seen.answers += 1;
        return json({ id: "x", question_id: QUESTION, status: "created", selected_option: 0, correct: true, correct_index: 0,
          evidence_segment_id: seg(1), evidence_quote: scenario.lines[0], explanation: "Nguồn." });
      }
      if (own === `/regions/${regionId}/result`) {
        const attempts = seen.dictation.length;
        return json({ region_id: regionId, practised: true, dictation_attempts: attempts, dictation_sentences: attempts, dictation_accuracy: 100,
          shadowing_attempts: seen.shadowing.length, shadowing_sentences: seen.shadowing.length, shadowing_average: 80,
          questions_answered: seen.answers, questions_correct: seen.answers, lookups: seen.lookups.length, words_saved: seen.saved.length });
      }
      unexpected.push(`${method} ${path}`);
      return route.abort();
    });

    await page.goto(`/library/videos/${ITEM}/watch`);
    // Bilingual subtitles: the server translates once, then the meaning sits under each original line.
    await expect(page.getByText("Nghĩa câu 1")).toBeVisible();
    await expect(page.locator(".transcript-row").first()).toContainText(scenario.lines[0]);
    expect(seen.translations).toBe(1);
    await page.getByRole("checkbox", { name: "Translation" }).uncheck();
    await expect(page.getByText("Nghĩa câu 1")).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Translation" }).check();
    await expect(page.locator(".region-bar")).toContainText("Cả đoạn");

    // Select a phrase in the first line: the meaning opens and the word can be saved with the part.
    await page.locator(".transcript-row").first().evaluate((row, phrase) => {
      const words = [...row.querySelectorAll<HTMLElement>("[data-cp]")];
      const first = words.find((node) => Number(node.dataset.cp) === phrase.start)!;
      const last = words.filter((node) => Number(node.dataset.cp) < phrase.end).at(-1)!;
      const range = document.createRange();
      range.setStart(first.firstChild!, 0);
      range.setEnd(last.firstChild!, last.textContent!.length);
      window.getSelection()!.removeAllRanges();
      window.getSelection()!.addRange(range);
      row.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    }, scenario.phrase);
    const lookup = page.getByRole("dialog");
    await expect(lookup).toContainText("kết thúc ở");
    await lookup.getByRole("button", { name: "Add to my words" }).click();
    await expect(lookup.getByRole("button", { name: /Saved to my words/ })).toBeVisible();
    await lookup.getByRole("button", { name: "Close" }).first().click();
    expect(seen.lookups).toHaveLength(1);
    expect(seen.lookups[0]).toMatchObject({ segment_id: seg(1), region_id: regionId });
    expect(seen.saved[0]).toMatchObject({ source: "lookup", library_item_id: ITEM, region_id: regionId });

    // Dictation.
    await page.getByRole("tab", { name: "Dictation" }).click();
    await page.getByRole("button", { name: "Hard · type it" }).click();
    await page.getByRole("button", { name: "Start dictation" }).click();
    await page.getByLabel("Type what you hear").fill(scenario.answer);
    await page.getByRole("button", { name: "Check", exact: true }).click();
    await expect.poll(() => seen.dictation.length).toBe(1);
    expect(seen.dictation[0]).toMatchObject({ segment_id: seg(1), region_id: regionId });

    // Shadowing (fake microphone).
    await page.getByRole("tab", { name: "Shadowing" }).click();
    await page.getByRole("button", { name: "Record", exact: true }).click();
    await page.waitForTimeout(1500);
    await page.getByRole("button", { name: /^Stop ·/ }).click();
    await expect(page.locator(".shadowing-result")).toBeVisible();
    expect(seen.shadowing).toHaveLength(1);
    expect(seen.shadowing[0]).toContain('name="region_id"');
    expect(seen.shadowing[0]).toContain(regionId);

    // Questions.
    await page.getByRole("tab", { name: "Questions" }).click();
    await page.locator(".question-card").first().getByRole("button").first().click();
    await expect(page.locator(".question-result").first()).toBeVisible();
    expect(seen.answers).toBe(1);

    // Result card: dictation accuracy, shadowing average, questions right and the new word.
    await page.locator(".region-bar").getByRole("button", { name: "Finish" }).click();
    const card = page.locator(".region-result");
    await expect(card).toContainText("100% of words right, 1 attempts");
    await expect(card).toContainText("Average score 80, 1 attempts");
    await expect(card).toContainText("1 of 1 right");
    await expect(card.getByText("New words saved")).toBeVisible();
    await expect(card.getByRole("link")).toHaveCount(0);
    await expect(page.locator(".agent-launcher").getByRole("link", { name: /^Talk about part \d+$/ }))
      .toHaveAttribute("href", new RegExp(`^/agent\\?mode=voice&entry=video&item=${ITEM}&segment=`));
    expect(unexpected).toEqual([]);
    expect(errors).toEqual([]);
  });
}

