// Shared live M1 proof. Uses learner UI only; no authority-state seeding.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const COMPANION_UTTERANCE_MS = 1500; // the product ignores utterances shorter than 400 ms

// Chromium flags that make getUserMedia answer with a fake device (no prompt). A live run needs real
// speech: E2E_COMPANION_AUDIO names a WAV played as the microphone. Without it only the beep device exists.
export function browserLaunchOptions(env = process.env) {
  const args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"];
  if (env.E2E_COMPANION_AUDIO) args.push(`--use-file-for-fake-audio-capture=${resolve(env.E2E_COMPANION_AUDIO)}`);
  return { headless: true, args };
}

// Source-traced provider paths of workspace(). This is an inventory, not enforcement.
// The occurrence Concept sheet/save and Quick review MCQ are deterministic/read-only-content paths;
// free-span lookup and dictionary search with translation are different actions, not driven here.
export const AI_CAPABLE_OPERATIONS = [
  { step: "library import (POST /learner/me/library/videos)",
    via: "LearnerLibraryService.import_video -> prepare_video + admit_video_content_work; a non-ready video can schedule transcript/preparation work",
    source: "backend/app/modules/content/application/library.py:84" },
  { step: "study part admission (PUT .../workspace/region)",
    via: "VideoWorkspaceService.save_region -> _admit -> region preparation worker; a matching prepared region is reused",
    source: "backend/app/modules/content/application/workspace.py:201" },
  { step: "Shadowing (POST .../shadowing/assessments)",
    via: "ShadowingPracticeService.assess -> configured AzurePronunciationAssessor.assess after ownership/VAD; non-evidential practice",
    source: "backend/app/modules/learning/application/shadowing.py" },
  { step: "Companion opening (POST /learner/me/companion/sessions)",
    via: "CompanionService.start -> _model_turn -> _turn_attempts, then optional Azure TTS; no speech transcription on opening",
    source: "backend/app/modules/learning/application/companion.py:197" },
  { step: "Companion learner turn and leaving (POST .../companion/turns/stream, .../companion/finish)",
    via: "turn -> speech transcription -> model/optional dictionary step -> optional TTS; closing or finish can propose memory only with consent",
    source: "backend/app/modules/learning/application/companion.py:229" },
];

// Live runs that can trigger the operations above stay blocked until a limit that covers the real call
// path (web -> API -> worker -> provider) exists for this candidate. The evidence is a JSON file.
export function assertAiLimitCovers(env = process.env) {
  const file = env.E2E_AI_LIMIT_EVIDENCE;
  const blocked = (why) => { throw new Error(`live_blocked: ${why}`); };
  if (!file) blocked("no AI limit evidence covering the web/API/worker call path (E2E_AI_LIMIT_EVIDENCE)");
  let evidence;
  try { evidence = JSON.parse(readFileSync(file, "utf8")); } catch { blocked("AI limit evidence unreadable"); }
  const need = ["api", "worker", "companion_provider"];
  if (evidence.candidate !== env.E2E_RELEASE_ID || !Array.isArray(evidence.covers) || need.some((p) => !evidence.covers.includes(p)))
    blocked(`AI limit evidence must name this candidate and cover ${need.join(", ")}`);
}

export function latencyStats(values, targetMs, minSamples = 20) {
  if (values.some((v) => !Number.isFinite(v) || v < 0)) throw new Error("Invalid latency sample");
  const sorted = [...values].sort((a, b) => a - b);
  const p95 = sorted.length >= minSamples ? sorted[Math.ceil(sorted.length * .95) - 1] : null;
  return { n: sorted.length, required_samples: minSamples, target_ms: targetMs, p95_ms: p95,
    max_ms: sorted.length ? sorted.at(-1) : null, target_met: p95 === null ? null : p95 <= targetMs };
}

export async function signIn(page, base, learner) {
  await page.goto(base + "/signin");
  await page.fill("#email", learner.email);
  await page.fill("#password", learner.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL(/\/(onboarding|home)$/);
  if (new URL(page.url()).pathname === "/onboarding") {
    await page.selectOption("#learning", process.env.E2E_LANGUAGE ?? "en");
    await page.selectOption("#support", "vi");
    await page.getByRole("button", { name: "Start learning" }).click();
  }
  await page.waitForURL("**/home");
  await page.getByRole("heading", { name: "Home", level: 1 }).waitFor();
  if (await page.getByRole("link", { name: "Open Review", exact: true }).count())
    throw new Error("Home is running the retired Review entry");
}

export async function verifyProductHome(page, base) {
  // Observe the application's reads; this proof never seeds learner state or accepts suggestions.
  const projections = Promise.all(["plan", "progress"].map(async (name) => {
    const response = await page.waitForResponse(r => r.request().method() === "GET" &&
      new URL(r.url()).pathname.endsWith("/learner/me/" + name));
    if (!response.ok()) throw new Error("Home projection unavailable: " + name);
    if (!/^Bearer\s+\S+$/i.test(response.request().headers().authorization ?? ""))
      throw new Error("Home projection request was not authenticated");
    const body = await response.json();
    if (!Array.isArray(body?.[name === "plan" ? "items" : "heatmap"]))
      throw new Error("Invalid Home projection: " + name);
    return body;
  }));
  projections.catch(() => {}); // Navigation failure must not leave rejected response waiters unhandled.
  await page.goto(base + "/home");
  await page.getByRole("heading", { name: "Home", level: 1 }).waitFor();
  const [plan, progress] = await projections;
  await page.getByRole("group", { name: "Activity", exact: true }).waitFor();
  await page.getByRole("group", { name: "Cards", exact: true }).waitFor();
  await page.waitForFunction(() => {
    const home = document.querySelector(".home-screen");
    return home?.getAttribute("aria-busy") === "false" && !home.querySelector(".home-skeleton");
  });
  const matches = await page.evaluate(({ plan, progress }) => {
    const home = document.querySelector(".home-screen");
    const featured = plan.items.find(item => item.status === "open" && item.kind === "video_practice");
    const today = new Date();
    const end = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const shown = [...home.querySelectorAll(".act-heatmap__grid .act-cell[title]")].map(el => el.getAttribute("title"));
    const expectedCells = shown.every(title => {
      const [date, attempts] = title.split(": ");
      return date <= end && Number(attempts) === (progress.heatmap.find(day => day.date === date)?.count ?? 0);
    });
    // The card count is the sum of the learner's decks.
    const totalCards = progress.cards.reduce((sum, deck) => sum + deck.total, 0);
    const shownCards = home.querySelector(".home-cards")?.getAttribute("aria-label");
    return home.querySelectorAll(".home-activity-card").length === 1 &&
      shown.length > 0 && expectedCells &&
      shownCards === `${totalCards} cards` &&
      home.querySelectorAll(".home-featured").length === (featured ? 1 : 0) &&
      (!featured || home.querySelector(".home-featured h2")?.textContent.trim() === (featured.video_title || "Watch a video"));
  }, { plan, progress });
  // Keep learner words, video titles and projection payloads out of failure logs.
  if (!matches) throw new Error("Home does not match server projections");
}

async function waitForQuestion(page, body) {
  const question = body.current_activity?.activity?.execution?.question;
  if (typeof question !== "string") throw new Error("Missing ready question");
  // The previous question may still be painted after the next HTTP response.
  // Wait for the expected text AND reset selection, not merely an existing radio.
  await page.waitForFunction((expected) => {
    const heading = document.querySelector(".activity-question");
    const first = document.querySelector('[role="radio"]');
    return heading?.textContent?.trim() === expected.trim() &&
      first?.getAttribute("aria-checked") === "false" && !first.hasAttribute("disabled");
  }, question);
}

export async function workspace(page, videoUrl, { tool = process.env.E2E_PRACTICE_TOOL ?? "dictation" } = {}) {
  if (!videoUrl) throw new Error("E2E_VIDEO_URL must name the approved prepared video");
  if (!["dictation", "companion", "shadowing", "questions", "all"].includes(tool))
    throw new Error("Unsupported M1 practice tool");
  // The Library was folded into Home (2026-11-05): the link form and the video list are there.
  await page.getByRole("link", { name: "Home", exact: true }).first().click();
  await page.getByLabel("Paste a YouTube link").fill(videoUrl);
  const imported = page.waitForResponse((r) => r.request().method() === "POST" &&
    new URL(r.url()).pathname.endsWith("/learner/me/library/videos"));
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const importResponse = await imported;
  if (!importResponse.ok()) throw new Error("Video import failed");
  const libraryId = (await importResponse.json()).item?.library_item_id;
  if (!/^[0-9a-f-]{36}$/i.test(libraryId ?? "")) throw new Error("Missing imported Library identity");
  const open = page.locator('a[href="/library/videos/' + libraryId + '/watch"]');
  // The run package must select an already prepared video/part. Import or admission
  // can schedule AI work; do not run this gate without the approved runtime budget.
  await open.waitFor({ timeout: 120000 });
  let selected = null;
  const trackRegion = async (response) => {
    if (!response.ok() || !/\/workspace(\/region)?$/.test(new URL(response.url()).pathname)) return;
    const body = await response.json().catch(() => null);
    if (body?.region) selected = body;
  };
  page.on("response", trackRegion);
  await open.click();
  await page.waitForURL("**/watch");
  await page.locator(".transcript-row").first().waitFor();
  // The study part is cut by AI and opened automatically; the region bar shows it once the server saved it.
  await page.locator(".region-bar").getByRole("button", { name: "Finish", exact: true }).waitFor({ timeout: 120000 });
  for (let attempt = 0; !selected?.region && attempt < 50; attempt++) await page.waitForTimeout(100);
  page.off("response", trackRegion);
  if (!selected?.region) throw new Error("Server did not save the study part");
  // Save up to three real, visible words through the normal learner action.
  const words = page.locator(".occurrence");
  await words.first().waitFor({ timeout: 120000 });
  let savedWords = 0;
  for (let i = 0; i < Math.min(await words.count(), 3); i++) {
    await words.nth(i).click();
    const sheet = page.getByRole("dialog", { name: "Concept", exact: true });
    await sheet.waitFor();
    const add = sheet.getByRole("button", { name: "Add to my words", exact: true });
    if (await add.count()) {
      await add.click();
      await sheet.getByRole("button", { name: /^(Saved to my words|Already known)$/ }).waitFor();
      savedWords++;
    }
    await sheet.getByRole("button", { name: "Close", exact: true }).click();
  }
  if (!savedWords) throw new Error("No dictionary-backed word was saved for Quick review");
  const tools = tool === "all" ? ["dictation", "shadowing", "questions", "companion"] : [tool];
  for (const activeTool of tools) {
    if (activeTool === "companion") {
      // Same requests the product client sends (companionApi.ts): open the conversation, then one real
      // learner turn. Opening alone records nothing, so the summary below must see a turn.
      await page.getByRole("button", { name: "Open agent", exact: true }).click();
      await page.getByLabel("More conversation tools", { exact: true }).click();
      await page.getByRole("button", { name: "Use recorded turns", exact: true }).click();
      const opened = page.waitForResponse((r) => r.request().method() === "POST" &&
        new URL(r.url()).pathname.endsWith("/learner/me/companion/sessions"));
      await page.getByRole("button", { name: "Start talking", exact: true }).click();
      const openResponse = await opened;
      if (!openResponse.ok()) throw new Error("Companion session did not open");
      const opening = await openResponse.json();
      if (typeof opening.session_ticket !== "string" || opening.finished !== false)
        throw new Error("Companion opening has no running session");
      const speak = page.getByRole("button", { name: "Tap to speak", exact: true });
      await speak.waitFor();
      const turned = page.waitForResponse((r) => r.request().method() === "POST" &&
        /\/learner\/me\/companion\/turns(\/stream)?$/.test(new URL(r.url()).pathname));
      await speak.click();
      const send = page.getByRole("button", { name: /^Tap to send/ });
      await send.waitFor();
      await page.waitForTimeout(COMPANION_UTTERANCE_MS);
      await send.click();
      const turnResponse = await turned;
      if (!turnResponse.ok()) throw new Error("Companion turn failed");
      // /turns/stream answers in NDJSON: the turn is the first line.
      const body = await turnResponse.text();
      const first = JSON.parse(body.split("\n").find((line) => line.trim()) ?? "{}");
      const turn = first.type === "turn" ? first.turn : first;
      if (typeof turn.learner_transcript !== "string" || !turn.learner_transcript.trim() || !(turn.turn >= 1))
        throw new Error("Server did not record a learner turn");
      await page.locator(".bubble.learner").first().waitFor();
      const finished = page.waitForResponse((r) => r.request().method() === "POST" &&
        new URL(r.url()).pathname.endsWith("/learner/me/companion/finish"));
      await page.getByRole("button", { name: "End conversation", exact: true }).click();
      if (!(await finished).ok()) throw new Error("Companion finish did not complete");
      await page.getByRole("button", { name: "Close agent", exact: true }).click();
    } else if (activeTool === "shadowing") {
      await page.getByRole("tab", { name: "Shadowing", exact: true }).click();
      const scored = page.waitForResponse((r) => r.request().method() === "POST" &&
        new URL(r.url()).pathname.endsWith("/shadowing/assessments"));
      await page.getByRole("button", { name: "Record", exact: true }).click();
      await page.waitForTimeout(COMPANION_UTTERANCE_MS);
      await page.getByRole("button", { name: /^Stop \u00b7/ }).click();
      if (!(await scored).ok()) throw new Error("Shadowing assessment failed");
      await page.locator(".shadowing-result").waitFor();
    } else if (activeTool === "questions") {
      await page.getByRole("tab", { name: "Questions", exact: true }).click();
      const option = page.locator(".question-card").first().getByRole("button").first();
      await option.waitFor();
      const checked = page.waitForResponse((r) => r.request().method() === "POST" &&
        /\/region-questions\/[^/]+\/answer$/.test(new URL(r.url()).pathname));
      await option.click();
      if (!(await checked).ok()) throw new Error("Region question answer failed");
      await page.locator(".question-result").first().waitFor();
    } else {
      await page.getByRole("tab", { name: "Dictation", exact: true }).click();
      await page.getByRole("button", { name: "Hard \u00b7 type it", exact: true }).click();
      await page.getByRole("button", { name: "Start dictation", exact: true }).click();
      await page.getByLabel("Type what you hear").fill("Synthetic practice response");
      const logged = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname.includes("/practice-events"));
      await page.getByRole("button", { name: "Check", exact: true }).click();
      if (!(await logged).ok()) throw new Error("Server did not record Dictation practice");
    }
  }
  await page.getByRole("tab", { name: "Transcript", exact: true }).click();
  // The part result is read back by the server from the learning log (GET .../regions/{region}/result).
  const summaryResponse = page.waitForResponse((r) => r.request().method() === "GET" && /\/regions\/[^/]+\/result$/.test(new URL(r.url()).pathname));
  await page.locator(".region-bar").getByRole("button", { name: "Finish", exact: true }).click();
  const response = await summaryResponse;
  if (!response.ok()) throw new Error("Region result failed");
  const summary = await response.json();
  const dictationSentences = summary.dictation_sentences ?? 0;
  const companionTurns = 0; // a talk with Tata is not part of the part result; its finish is confirmed above
  // The tool that was driven must be what the server counted; the other tool cannot stand in for it.
  const counts = { dictation: dictationSentences, shadowing: summary.shadowing_sentences ?? 0,
    questions: summary.questions_answered ?? 0 };
  if (summary.practised !== true && !tools.every((kind) => kind === "companion") || tools.some((kind) => kind !== "companion" && counts[kind] < 1))
    throw new Error("Server did not confirm a completed practice session");
  await page.locator(".region-result").waitFor();
  return {
    server_completed: true,
    dictation_sentences: dictationSentences,
    companion_turns: companionTurns,
    shadowing_sentences: summary.shadowing_sentences ?? 0,
    questions_answered: summary.questions_answered ?? 0,
    practice_tool: tool,
    practice_tools: tools,
    companion_finish_confirmed: tools.includes("companion"),
    saved_words: savedWords,
    selected_segment_count: selected.region.segment_count,
  };
}
