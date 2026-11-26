import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  BUILD_INPUTS, REQUIRED_CONFIG, REQUIRED_GATES, VERIFICATION_INPUTS, buildManifest, configFromEnv, distFingerprint,
  fingerprint, parseCounts,
} from "./release_lib.mjs";
import { runGate } from "./run-gate.mjs";

const API = "/api/v1/v3";
const SUPABASE = "https://project.supabase.co";
const ENV = { VITE_API_BASE_URL: API, VITE_SUPABASE_URL: SUPABASE, VITE_SUPABASE_PUBLISHABLE_KEY: "pk-secret-value" };

function put(root, rel, text) {
  const file = join(root, rel);
  mkdirSync(join(file, ".."), { recursive: true });
  writeFileSync(file, text);
}

// A project whose build record and gate evidence are produced by the same code the real tools use.
function project({ env = ENV, gates = REQUIRED_GATES } = {}) {
  const root = mkdtempSync(join(tmpdir(), "m1-release-"));
  put(root, "src/main.ts", "export {}");
  put(root, "index.html", "<html></html>");
  put(root, "package.json", "{}");
  put(root, "package-lock.json", "{}");
  put(root, "vite.config.ts", "export default {}");
  put(root, "tsconfig.json", "{}");
  put(root, "tsconfig.node.json", "{}");
  put(root, "e2e/a.spec.ts", "x");
  put(root, "scripts/a.mjs", "x");
  put(root, "playwright.config.ts", "x");
  put(root, "dist/assets/index.js", `const a="${env.VITE_API_BASE_URL ?? ""}",b="${env.VITE_SUPABASE_URL ?? ""}";`);
  writeRecord(root, env);
  for (const gate of gates) writeEvidence(root, gate);
  return root;
}

function writeRecord(root, env) {
  put(root, "release/build-record.json", JSON.stringify({
    built_at: "2026-10-23T00:00:00Z", build_inputs: fingerprint(root, BUILD_INPUTS), dist: distFingerprint(root),
    config: configFromEnv(env), toolchain: { node: "test" },
  }));
}

function writeEvidence(root, gate, overrides = {}) {
  put(root, `release/evidence/${gate}.json`, JSON.stringify({
    gate, command: gate, exit_code: 0, finished_at: "2026-10-23T00:00:00Z", counts: { passed: 3, failed: 0 },
    verification_inputs: fingerprint(root, VERIFICATION_INPUTS).sha256,
    dist_sha256: distFingerprint(root).sha256, output_sha256: "0", ...overrides,
  }));
}

const make = (root, extra = {}) => buildManifest({ root, git: { head_commit: "abc", dirty_in_web: false }, ...extra });

test("a candidate is ready only when build, configuration and every gate derive as passed", () => {
  const { manifest, blockers } = make(project());
  assert.deepEqual(blockers, []);
  assert.equal(manifest.status, "ready_for_staging");
  assert.equal(manifest.configuration.values.VITE_SUPABASE_URL, SUPABASE);
  // The publishable key is never written: presence and a short hash only.
  assert.ok(!JSON.stringify(manifest).includes("pk-secret-value"));
  assert.equal(manifest.gates.unit.counts.passed, 3);
});

test("the candidate id depends on build inputs, never on git, so no commit can contain its own id", () => {
  const root = project();
  const a = make(root).manifest.release_candidate_id;
  const b = buildManifest({ root, git: { head_commit: "other", dirty_in_web: true } }).manifest.release_candidate_id;
  assert.equal(a, b);
  put(root, "src/main.ts", "export const changed = 1");
  assert.notEqual(make(root).manifest.release_candidate_id, a);
});

test("an old dist, a missing record and edited output are blocked, not trusted", () => {
  const stale = project();
  put(stale, "src/main.ts", "export const changed = 1"); // sources moved on after the build
  assert.match(make(stale).blockers.join("\n"), /build: sources changed since the recorded build/);

  const edited = project();
  put(edited, "dist/assets/index.js", "tampered");
  assert.match(make(edited).blockers.join("\n"), /build: dist differs from the recorded build output/);

  const unrecorded = project();
  put(unrecorded, "release/build-record.json", "not json");
  const m = make(unrecorded);
  assert.equal(m.manifest.status, "blocked");
  assert.match(m.blockers.join("\n"), /configuration unknown/);
});

test("missing or mismatching build configuration blocks and is reported as unknown/missing/failed", () => {
  const missing = project({ env: { ...ENV, VITE_SUPABASE_URL: undefined } });
  const m = make(missing);
  assert.equal(m.manifest.configuration.checks.VITE_SUPABASE_URL.status, "missing");
  assert.equal(m.manifest.status, "blocked");

  // The record claims a URL that the bundle does not contain.
  const lying = project();
  put(lying, "release/build-record.json", JSON.stringify({
    build_inputs: fingerprint(lying, BUILD_INPUTS), dist: distFingerprint(lying),
    config: configFromEnv({ ...ENV, VITE_SUPABASE_URL: "https://elsewhere.supabase.co" }),
  }));
  const l = make(lying);
  assert.equal(l.manifest.configuration.checks.VITE_SUPABASE_URL.status, "failed");

  const extra = project({ env: { ...ENV, VITE_UNEXPECTED: "1" } });
  assert.match(make(extra).blockers.join("\n"), /unexpected VITE_ variables at build: VITE_UNEXPECTED/);
  assert.deepEqual(REQUIRED_CONFIG.length, 3);
});

test("gates that did not run, failed, or ran on other inputs block the candidate", () => {
  const notRun = project({ gates: REQUIRED_GATES.filter((g) => g !== "e2e_deterministic") });
  assert.equal(make(notRun).manifest.gates.e2e_deterministic.status, "not_run");

  const failed = project();
  writeEvidence(failed, "unit", { exit_code: 1 });
  assert.equal(make(failed).manifest.gates.unit.status, "failed");

  const failedCount = project();
  writeEvidence(failedCount, "unit", { counts: { passed: 3, failed: 1 } });
  assert.equal(make(failedCount).manifest.gates.unit.status, "failed");

  const stale = project();
  put(stale, "e2e/a.spec.ts", "edited after the run");
  assert.equal(make(stale).manifest.gates.unit.status, "stale");

  const distChanged = project();
  writeEvidence(distChanged, "audit", { dist_sha256: "0".repeat(64) });
  assert.equal(make(distChanged).manifest.gates.audit.status, "stale");
});

test("live stays blocked unless evidence names this candidate and covers api, worker and provider", () => {
  const root = project();
  const base = make(root);
  assert.equal(base.manifest.live.status, "blocked");
  const id = base.manifest.release_candidate_id;
  put(root, "ai.json", JSON.stringify({ candidate: id, covers: ["api"] }));
  assert.match(make(root, { aiLimitEvidence: join(root, "ai.json") }).manifest.live.reasons.join("\n"), /does not cover/);
  put(root, "ai.json", JSON.stringify({ candidate: "other", covers: ["api", "worker", "companion_provider"] }));
  assert.match(make(root, { aiLimitEvidence: join(root, "ai.json") }).manifest.live.reasons.join("\n"), /another candidate/);
  put(root, "ai.json", JSON.stringify({ candidate: id, covers: ["api", "worker", "companion_provider"] }));
  assert.equal(make(root, { aiLimitEvidence: join(root, "ai.json") }).manifest.live.status, "limit_evidence_present");
});

test("run-gate records the real exit code, counts and input hashes", () => {
  const root = project({ gates: [] });
  const ok = runGate("unit", `node -e "console.log('Tests  7 passed (7)')"`, root, { echo: false });
  assert.equal(ok.exit_code, 0);
  assert.deepEqual(ok.counts, { passed: 7, failed: 0 });
  const bad = runGate("typecheck", `node -e "process.exit(3)"`, root, { echo: false });
  assert.equal(bad.exit_code, 3);
  assert.equal(bad.counts, null);
  assert.equal(bad.verification_inputs, fingerprint(root, VERIFICATION_INPUTS).sha256);
});

test("counts come from each runner's own summary and are null when unreadable", () => {
  assert.deepEqual(parseCounts("Tests  389 passed (389)"), { passed: 389, failed: 0 });
  assert.deepEqual(parseCounts("  44 passed (26.9s)"), { passed: 44, failed: 0 });
  assert.deepEqual(parseCounts("ℹ pass 11\nℹ fail 1"), { passed: 11, failed: 1 });
  assert.deepEqual(parseCounts("\u001b[2m      Tests \u001b[22m \u001b[1m\u001b[32m69 passed\u001b[39m\u001b[22m (69)"), { passed: 69, failed: 0 });
  // A test title that merely quotes a summary line must not be read as the runner's own count.
  assert.deepEqual(parseCounts("✔ title Tests  7 passed (7) (1ms)\nℹ pass 19\nℹ fail 0"), { passed: 19, failed: 0 });
  assert.equal(parseCounts("nothing"), null);
});
