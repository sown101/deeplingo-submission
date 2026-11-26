import assert from "node:assert/strict";
import test from "node:test";
import { latencyStats } from "./m1_runtime_helpers.mjs";

test("missing/short samples never claim the latency gate passed", () => {
  assert.equal(latencyStats([], 300).target_met, null);
  assert.equal(latencyStats([20, 30], 300).p95_ms, null);
});
test("p95 uses whole measured click-to-render durations", () => {
  assert.equal(latencyStats(Array(20).fill(299), 300).target_met, true);
  assert.equal(latencyStats([...Array(18).fill(20), 400, 500], 300).target_met, false);
});
test("invalid samples cannot disappear from a report", () => {
  for (const bad of [NaN, Infinity, -1]) assert.throws(() => latencyStats([bad], 300));
});

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AI_CAPABLE_OPERATIONS, assertAiLimitCovers, browserLaunchOptions } from "./m1_runtime_helpers.mjs";

test("live runs stay blocked without limit evidence that covers api, worker and provider for this candidate", () => {
  assert.throws(() => assertAiLimitCovers({}), /live_blocked/);
  const dir = mkdtempSync(join(tmpdir(), "ai-limit-"));
  const write = (body) => { const f = join(dir, "e.json"); writeFileSync(f, JSON.stringify(body)); return f; };
  const env = (body) => ({ E2E_RELEASE_ID: "c1", E2E_AI_LIMIT_EVIDENCE: write(body) });
  assert.throws(() => assertAiLimitCovers(env({ candidate: "c1", covers: ["api"] })), /live_blocked/);
  assert.throws(() => assertAiLimitCovers(env({ candidate: "other", covers: ["api", "worker", "companion_provider"] })), /live_blocked/);
  assert.doesNotThrow(() => assertAiLimitCovers(env({ candidate: "c1", covers: ["api", "worker", "companion_provider"] })));
});

test("AI-capable operations are listed and borrow no limit from the record harness", () => {
  const text = JSON.stringify(AI_CAPABLE_OPERATIONS);
  assert.ok(AI_CAPABLE_OPERATIONS.length >= 4);
  assert.doesNotMatch(text, /BoundedEgress|1\.25/);
});

test("browser launch uses the fake microphone and an explicit audio file only when named", () => {
  assert.deepEqual(browserLaunchOptions({}).args, ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]);
  assert.ok(browserLaunchOptions({ E2E_COMPANION_AUDIO: "a.wav" }).args.some((a) => a.startsWith("--use-file-for-fake-audio-capture=")));
});
