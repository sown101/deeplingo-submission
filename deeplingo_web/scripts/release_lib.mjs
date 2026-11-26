// Evidence-based release candidate report for deeplingo_web.
//
// Nothing here is a constant verdict: every status is derived from files that a build or a test run
// wrote (release/build-record.json, release/evidence/<gate>.json) and is compared with the inputs and
// the dist that exist now. Missing, stale or failed evidence makes the candidate "blocked".
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export const SCHEMA = 1;

// What goes into the built bundle.
export const BUILD_INPUTS = ["src", "public", "index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig*.json"];
// Absent without consequence (the app has no static public/ assets today).
export const OPTIONAL_INPUTS = ["public"];
// What the gates exercise: the build inputs plus the tests, helpers and runner configuration.
export const VERIFICATION_INPUTS = [...BUILD_INPUTS, "e2e", "scripts", "playwright.config.ts", "eslint.config.js"];

export const REQUIRED_GATES = ["typecheck", "unit", "node_helpers", "e2e_deterministic", "bundle", "audit"];
// Gates that read dist: their evidence is bound to the dist that existed when they ran.
export const DIST_GATES = ["bundle", "audit"];

export const REQUIRED_CONFIG = ["VITE_API_BASE_URL", "VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY"];
const SECRET_CONFIG = new Set(["VITE_SUPABASE_PUBLISHABLE_KEY"]);

const TEXT = /\.(?:[cm]?[jt]sx?|json|css|html|md|svg|txt|mjs|cjs)$/i;
const sha = (data) => createHash("sha256").update(data).digest("hex");
const posix = (p) => p.split("\\").join("/");

function* walk(dir) {
  for (const name of readdirSync(dir).sort()) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) yield* walk(full);
    else yield full;
  }
}

function matches(root, entry) {
  if (!entry.includes("*")) return [entry];
  const re = new RegExp(`^${entry.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")}$`);
  return readdirSync(root).filter((n) => re.test(n));
}

function content(file) {
  const raw = readFileSync(file);
  // Line endings differ between checkouts; they are not part of what was built or tested.
  return TEXT.test(file) ? Buffer.from(raw.toString("utf8").replace(/\r\n/g, "\n")) : raw;
}

export function fingerprint(root, entries) {
  const files = [];
  const missing = [];
  for (const entry of entries.flatMap((e) => matches(root, e))) {
    const full = join(root, entry);
    if (!existsSync(full)) { missing.push(entry); continue; }
    if (statSync(full).isDirectory()) files.push(...walk(full));
    else files.push(full);
  }
  const hash = createHash("sha256");
  const names = files.map((f) => posix(relative(root, f))).sort();
  for (const name of names) hash.update(`${name}\0${sha(content(join(root, name)))}\n`);
  return { sha256: hash.digest("hex"), files: names.length, missing };
}

export function distFingerprint(root) {
  const dist = join(root, "dist");
  if (!existsSync(dist)) return null;
  const hash = createHash("sha256");
  const names = [...walk(dist)].map((f) => posix(relative(dist, f))).sort();
  for (const name of names) hash.update(`${name}\0${sha(readFileSync(join(dist, name)))}\n`);
  return { sha256: hash.digest("hex"), files: names.length };
}

export function readJson(file) {
  if (!existsSync(file)) return { missing: true };
  try { return { value: JSON.parse(readFileSync(file, "utf8")) }; } catch { return { invalid: true }; }
}

// Counts are read from the runner's own summary line; unreadable output yields null, never a guess.
export function parseCounts(raw) {
  const output = raw.replace(/\u001b\[[0-9;]*m/g, ""); // runners colour their summary lines
  const n = (re) => { const m = output.match(re); return m ? Number(m[1]) : null; };
  const node = n(/ℹ pass (\d+)/);
  if (node !== null) return { passed: node, failed: n(/ℹ fail (\d+)/) ?? 0 };
  const vitest = n(/^\s*Tests\s+(\d+) passed/m);
  if (vitest !== null) return { passed: vitest, failed: n(/^\s*Tests\s+(\d+) failed/m) ?? 0 };
  const pw = n(/^\s*(\d+) passed/m);
  if (pw !== null) return { passed: pw, failed: n(/^\s*(\d+) failed/m) ?? 0 };
  return null;
}

export function configFromEnv(env) {
  const config = {};
  for (const key of REQUIRED_CONFIG) {
    const value = env[key];
    config[key] = value === undefined || value === ""
      ? null
      : SECRET_CONFIG.has(key) ? { present: true, sha256_prefix: sha(value).slice(0, 8) } : value;
  }
  const other = Object.keys(env).filter((k) => k.startsWith("VITE_") && !REQUIRED_CONFIG.includes(k)).sort();
  return { values: config, other_vite_variables: other };
}

function distText(root) {
  const dist = join(root, "dist");
  return [...walk(dist)].filter((f) => /\.(?:js|html)$/.test(f)).map((f) => readFileSync(f, "utf8")).join("\n");
}

const check = (status, detail) => ({ status, detail });

// problems = reasons the candidate cannot go to staging; the manifest is still written.
export function buildManifest({ root, git, aiLimitEvidence, now = new Date() }) {
  const blockers = [];
  const block = (m) => blockers.push(m);
  const build = fingerprint(root, BUILD_INPUTS);
  const verification = fingerprint(root, VERIFICATION_INPUTS);
  const candidateId = `web-${build.sha256.slice(0, 12)}`;
  const requiredMissing = build.missing.filter((m) => !OPTIONAL_INPUTS.includes(m));
  if (requiredMissing.length) block(`build inputs missing: ${requiredMissing.join(", ")}`);

  // --- build record vs current inputs and dist
  const record = readJson(join(root, "release", "build-record.json"));
  const dist = distFingerprint(root);
  let buildCheck;
  if (record.missing || record.invalid) buildCheck = check("missing", "release/build-record.json absent or unreadable: run npm run build:release");
  else if (!dist) buildCheck = check("missing", "dist/ absent");
  else if (record.value.build_inputs?.sha256 !== build.sha256) buildCheck = check("stale", "sources changed since the recorded build");
  else if (record.value.dist?.sha256 !== dist.sha256) buildCheck = check("stale", "dist differs from the recorded build output");
  else buildCheck = check("passed", `dist ${dist.sha256.slice(0, 12)} built from inputs ${build.sha256.slice(0, 12)}`);
  if (buildCheck.status !== "passed") block(`build: ${buildCheck.detail}`);

  // --- configuration actually used by the build
  const used = record.value?.config;
  const configuration = { recorded: Boolean(used), values: used?.values ?? null, other_vite_variables: used?.other_vite_variables ?? null,
    checks: {} };
  if (!used) {
    for (const key of REQUIRED_CONFIG) configuration.checks[key] = check("unknown", "no build record");
    block("configuration unknown: no build record");
  } else {
    const text = buildCheck.status === "passed" ? distText(root) : null;
    for (const key of REQUIRED_CONFIG) {
      const value = used.values?.[key];
      if (value === null || value === undefined) { configuration.checks[key] = check("missing", "not set at build"); block(`configuration: ${key} was not set at build`); continue; }
      if (SECRET_CONFIG.has(key)) { configuration.checks[key] = check("recorded", "presence only"); continue; }
      if (text === null) configuration.checks[key] = check("unknown", "dist not verified");
      else if (!text.includes(value)) { configuration.checks[key] = check("failed", "value not found in dist"); block(`configuration: ${key} recorded at build is not in dist`); }
      else configuration.checks[key] = check("passed", "value found in dist");
    }
    if (used.other_vite_variables?.length) block(`configuration: unexpected VITE_ variables at build: ${used.other_vite_variables.join(", ")}`);
  }

  // --- gates
  const gates = {};
  for (const name of REQUIRED_GATES) {
    const ev = readJson(join(root, "release", "evidence", `${name}.json`));
    if (ev.missing || ev.invalid) { gates[name] = { status: "not_run", detail: "no evidence file" }; block(`gate ${name}: not run`); continue; }
    const e = ev.value;
    const base = { command: e.command, exit_code: e.exit_code, counts: e.counts ?? null, finished_at: e.finished_at, output_sha256: e.output_sha256 };
    if (e.verification_inputs !== verification.sha256) gates[name] = { ...base, status: "stale", detail: "inputs changed since this run" };
    else if (DIST_GATES.includes(name) && (!dist || e.dist_sha256 !== dist.sha256)) gates[name] = { ...base, status: "stale", detail: "dist changed since this run" };
    else if (e.exit_code !== 0 || (e.counts && e.counts.failed > 0)) gates[name] = { ...base, status: "failed", detail: `exit ${e.exit_code}` };
    else gates[name] = { ...base, status: "passed", detail: "bound to current inputs" };
    if (gates[name].status !== "passed") block(`gate ${name}: ${gates[name].status} (${gates[name].detail})`);
  }

  // --- live: a separate verdict that this report never grants on its own
  const live = { status: "blocked", reasons: [] };
  if (!aiLimitEvidence) live.reasons.push("no evidence that a limit covers the real AI call path (api, worker, companion_provider)");
  else {
    const ev = readJson(aiLimitEvidence);
    const need = ["api", "worker", "companion_provider"];
    if (!ev.value) live.reasons.push("AI limit evidence unreadable");
    else if (ev.value.candidate !== candidateId) live.reasons.push("AI limit evidence names another candidate");
    else if (need.some((p) => !(ev.value.covers ?? []).includes(p))) live.reasons.push(`AI limit evidence does not cover ${need.join(", ")}`);
    else live.status = "limit_evidence_present";
  }
  live.reasons.push("no live qualification evidence is read by this report");

  return {
    blockers,
    manifest: {
      schema: SCHEMA,
      release_candidate_id: candidateId,
      generated_at: now.toISOString(),
      status: blockers.length ? "blocked" : "ready_for_staging",
      blockers,
      git: git ?? { head_commit: "unknown", dirty_in_web: null },
      build_inputs: build,
      verification_inputs: verification,
      build: { check: buildCheck, recorded_at: record.value?.built_at ?? null, toolchain: record.value?.toolchain ?? null },
      dist,
      configuration,
      gates,
      live,
    },
  };
}
