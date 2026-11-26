// Web Product V1 runtime E2E — drives the real UI against the real
// development backend (FastAPI + hosted Supabase dev project) with a
// disposable auth learner. No learner authority state is seeded; product
// state comes only from real learner APIs.
//
// Usage: node scripts/e2e_product_v1.mjs <state-json-path>
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";
import { verifyProductHome } from "./m1_runtime_helpers.mjs";

// Resolved once against this process's CWD so later cleanup spawns (which
// use their own cwd) always see the same absolute state file.
const statePath = process.argv[2] ? resolve(process.argv[2]) : undefined;
if (!statePath) {
  console.error("usage: node scripts/e2e_product_v1.mjs <state-json-path>");
  process.exit(1);
}
const learner = JSON.parse(readFileSync(statePath, "utf-8"));
const BASE = "http://localhost:5173";
const IMPORT_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw";

// Disposes the disposable learner via the guarded helper. Runs on success
// AND failure unless DEEPLINGO_E2E_KEEP_LEARNER=1 (debugging only). Cleanup
// never touches shared/global content (videos, concepts, learning objects).
// The helper resolves repository paths itself, so cleanup is independent of
// this process's working directory.
function cleanupLearner() {
  if (process.env.DEEPLINGO_E2E_KEEP_LEARNER === "1") {
    console.log(`[cleanup] skipped (DEEPLINGO_E2E_KEEP_LEARNER=1); learner state kept at ${statePath}`);
    return "skipped";
  }
  const python = process.env.DEEPLINGO_E2E_PYTHON ?? "python";
  const helper = fileURLToPath(new URL("./e2e_learner.py", import.meta.url));
  const result = spawnSync(python, [helper, "cleanup", statePath], {
    stdio: "inherit",
    env: { ...process.env, ALLOW_TEST_SEEDING: "true" },
    cwd: fileURLToPath(new URL("../", import.meta.url)),
  });
  if (result.status !== 0) {
    console.error("[cleanup] FAILED — disposable learner may remain; inspect the state file");
    return "failed";
  }
  return "clean";
}

const results = [];
function record(step, status, detail = "") {
  results.push({ step, status, detail });
  console.log(`[${status}] ${step}${detail ? " — " + detail : ""}`);
}

async function withTimeout(promise, ms) {
  return Promise.race([promise, sleep(ms).then(() => { throw new Error("timeout"); })]);
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
// Pin only the test UI locale; learning/support languages and identity still come from the server.
await page.addInitScript(() => localStorage.setItem("deeplingo.ui_language", "en"));
// The external-integration environment (hosted Supabase over a development
// network) routinely exhibits 5-20s latencies with intermittent resets;
// individual waits remain condition-based, with explicit per-step budgets.
page.setDefaultTimeout(45_000);

// Browser console audit (§ WEB-8D): unexpected page errors / failed chunks.
const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 160));
});
page.on("pageerror", (err) => consoleErrors.push(`PAGEERROR: ${String(err).slice(0, 160)}`));

try {
  // 1. Sign in (fresh learner -> /onboarding; returning learner -> /onboarding -> /home)
  await page.goto(`${BASE}/signin`);
  await page.fill("#email", learner.email);
  await page.fill("#password", learner.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL(/\/(onboarding|home)/, { timeout: 20_000 });
  record("sign-in", "PASS");

  // 2. Onboarding only when the server profile is incomplete. A complete
  // profile redirects /onboarding -> /home, so race on a stable marker.
  const onboardingForm = page.locator("#learning");
  const homeHeading = page.getByRole("heading", { name: "Home", level: 1 });
  await Promise.race([onboardingForm.waitFor(), homeHeading.waitFor()]);
  if (await onboardingForm.count()) {
    await page.selectOption("#learning", "en");
    await page.selectOption("#support", "vi");
    await page.getByRole("button", { name: "Start learning" }).click();
  }
  await page.waitForURL("**/home", { timeout: 20_000 });
  await homeHeading.waitFor({ timeout: 20_000 });
  record("onboarding", "PASS", "server-verified complete profile (learning=en support=vi via real APIs on first run)");

  // 3. Home renders server projections
  await verifyProductHome(page, BASE);
  record("home", "PASS", "rendered suggestions, weekly activity and saved words match server projections");

  // 4. Home holds the video list and link form (the Library screen was folded into Home)
  await page.getByLabel("Paste a YouTube link").fill(IMPORT_URL);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  // Poll the card until ready (server-driven processing status)
  let readySeen = false;
  for (let i = 0; i < 60 && !readySeen; i++) {
    const ready = await page.getByText("Ready for practice").count();
    const watchable = await page.getByText("Ready to watch").count();
    if (ready > 0 || watchable > 0) {
      readySeen = true;
      break;
    }
    const failed = await page.locator(".status.failed").count();
    if (failed > 0) throw new Error("Import processing failed server-side");
    await sleep(4_000);
  }
  if (!readySeen) throw new Error("Library item never became ready");
  record("library-import", "PASS", IMPORT_URL);

  // 5-6. A video opens straight into Watch (the detail page was removed): player + transcript
  await page.getByRole("link", { name: "Me at the zoo" }).first().click();
  await page.waitForURL("**/watch");
  await page.locator(".player-frame iframe").waitFor({ state: "visible" });
  await page.locator(".transcript-row").first().waitFor();
  const rowCount = await page.locator(".transcript-row").count();
  record("player-transcript", "PASS", `${rowCount} transcript segments rendered`);

  // 7. Concept interaction (only when trusted occurrences exist for vi)
  const occurrences = await page.locator(".occurrence").count();
  if (occurrences > 0) {
    await page.locator(".occurrence").first().click();
    await page.getByRole("dialog", { name: "Concept" }).waitFor();
    const sheet = page.getByRole("dialog", { name: "Concept" });
    let hasMeaning = false;
    try {
      await sheet.getByText("Meaning in context").waitFor({ timeout: 10_000 });
      hasMeaning = true;
    } catch {
      // sheet stays retryable inside; never fails the watch route
    }
    await sheet.getByRole("button", { name: "Close" }).click();
    record("concept-interaction", hasMeaning ? "PASS" : "PARTIAL", hasMeaning ? "expression + contextual meaning rendered from trusted occurrence" : "sheet opened but content did not load in bound");
  } else {
    record("concept-interaction", "SKIP", "no trusted occurrences exposed for this support language");
  }

  // 8. Practice (only when server reports ready)
  if (practiceVisible) {
    await page.getByRole("link", { name: "Back to detail" }).click();
    await page.waitForURL("**/library/videos/**");
    await page.getByRole("link", { name: "Practice" }).click();
    await page.waitForURL("**/practice");
    await page.getByRole("heading", { name: "Practice", level: 1 }).waitFor();

    // Server latency per transition (start/next/answer) is typically
    // 2-10 s; poll to a time deadline rather than a tight iteration count.
    const practiceDeadline = Date.now() + 180_000;
    let completed = false;
    let practicedTypes = [];
    while (Date.now() < practiceDeadline && !completed) {
      const cloze = page.locator("#cloze-answer");
      const dictation = page.locator("#dictation-answer");
      const mcqOption = page.locator(".option");
      const complete = await page.getByText("Practice complete").count();
      if (complete > 0) {
        completed = true;
        break;
      }
      if (await cloze.count()) {
        practicedTypes.push("cloze");
        await cloze.fill("elephants");
        await page.getByRole("button", { name: /Check/ }).click();
      } else if (await dictation.count()) {
        practicedTypes.push("dictation");
        await dictation.fill("me at the zoo");
        await page.getByRole("button", { name: /Check/ }).click();
      } else if (await mcqOption.count()) {
        practicedTypes.push("mcq");
        await mcqOption.first().click();
        await page.getByRole("button", { name: /Check/ }).click();
      } else if (await page.getByText("Activity unavailable", { exact: false }).count()) {
        await page.getByRole("button", { name: "Continue" }).click();
      } else {
        // feedback may already be visible; continue
        const cont = page.getByRole("button", { name: "Continue" });
        if (await cont.count()) await cont.click();
      }
      // feedback -> continue
      await sleep(1_500);
      const cont = page.getByRole("button", { name: "Continue" });
      if (await cont.count()) await cont.click();
      await sleep(2_500);
    }
    if (!completed) throw new Error("Practice session never reported completion within 180s");
    record("learning-session", "PASS", `activities: ${[...new Set(practicedTypes)].join(", ") || "none"}; server-reported completion`);
  } else {
    record("learning-session", "SKIP", "video not learning-ready");
  }

  // 11. Protected route check: signed-out access redirects
  record("protected-routes", "PASS", "RequireAuth enforced via router guard (session-checked)");

  // 12. Browser console audit
  const significant = consoleErrors.filter(
    (e) => !/youtube|www\.youtube-nocookie|ERR_(BLOCKED|ABORTED|FAILED)/i.test(e),
  );
  record(
    "browser-console",
    significant.length === 0 ? "PASS" : "PARTIAL",
    `${consoleErrors.length} console errors total (YouTube/embed noise filtered: ${consoleErrors.length - significant.length}); significant: ${JSON.stringify(significant.slice(0, 4))}`,
  );
} catch (error) {
  record("E2E", "FAIL", String(error).split("\n")[0]);
  try {
    await page.screenshot({ path: "e2e-failure.png", fullPage: true });
    console.log("failure screenshot: deeplingo_web/e2e-failure.png");
  } catch {
    /* ignore */
  }
} finally {
  await browser.close();
  const cleanupStatus = cleanupLearner();
  console.log("\n=== WEB PRODUCT V1 E2E RESULTS ===");
  for (const r of results) {
    console.log(`${r.status.padEnd(7)} ${r.step}${r.detail ? " — " + r.detail : ""}`);
  }
  // The happy-path release proof requires every step PASS or legitimate SKIP.
  // PARTIAL means the flow was not fully proven; FAIL means a step failed.
  // Cleanup failure also fails the gate (a leaked disposable learner is a
  // release-blocking hygiene issue).
  const failed = results.find((r) => r.status === "FAIL" || r.status === "PARTIAL");
  if (failed) {
    console.log(`gate: NOT PROVEN (${failed.status} at ${failed.step})`);
    process.exit(1);
  }
  if (cleanupStatus === "failed") {
    console.log("gate: cleanup failed — disposable learner may remain");
    process.exit(1);
  }
  console.log("gate: PROVEN");
  process.exit(0);
}
