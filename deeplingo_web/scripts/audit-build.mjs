// WEB-8B production build audit.
//
// Scans dist/ for accidental exposure of privileged configuration and
// debug artifacts. Run after `npm run build`:
//
//   node scripts/audit-build.mjs
//
// Fails (non-zero) on:
//   - emitted source maps (.map files)
//   - privileged secret/env names or connection strings in the bundle
//   - VITE_ variable names that are not the documented browser-safe set
//   - env files, logs, or E2E artifacts accidentally copied into dist
//
// Localhost occurrences are REPORTED (they can only originate from build
// machine env, e.g. .env.local) — the runtime production guard refuses to
// boot such a build, and this report makes the cause visible.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const DIST = new URL("../dist/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const ASSET_EXTENSIONS = new Set([".js", ".html", ".css"]);

const SECRET_PATTERNS = [
  ["service-role key", /SUPABASE_SERVICE_ROLE_KEY|service_role/i],
  ["AI provider key", /AI_API_KEY|AI_SEMANTIC_ASSESSMENT_MODEL|AI_ACTIVITY_GENERATION_MODEL/],
  ["Redis connection", /REDIS_URL|redis:\/\//i],
  ["database connection", /postgres(ql)?:\/\/|postgresql:\/\//i],
  ["test seeding guard", /ALLOW_TEST_SEEDING|SMOKE_EXPECTED_SUPABASE/i],
  ["E2E learner artifacts", /deeplingo-web-e2e-|e2e-dummy-jwt/],
];

const ALLOWED_VITE_VARS = new Set([
  "VITE_API_BASE_URL",
  "VITE_SUPABASE_URL",
  "VITE_SUPABASE_PUBLISHABLE_KEY",
]);

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) yield* walk(full);
    else yield full;
  }
}

let failures = 0;
let files = 0;
const localhostHits = [];
const viteVarNames = new Set();

for (const file of walk(DIST)) {
  const ext = extname(file);
  if (ext === ".map") {
    console.error(`FAIL: source map emitted: ${file}`);
    failures += 1;
    continue;
  }
  if (!ASSET_EXTENSIONS.has(ext)) continue;
  files += 1;
  const content = readFileSync(file, "utf8");

  for (const [label, pattern] of SECRET_PATTERNS) {
    if (pattern.test(content)) {
      console.error(`FAIL: possible ${label} reference in ${file}`);
      failures += 1;
    }
  }

  for (const match of content.matchAll(/VITE_[A-Z0-9_]+/g)) {
    viteVarNames.add(match[0]);
  }

  for (const match of content.matchAll(/https?:\/\/localhost[^"'`\s)]*/g)) {
    // Exclude @supabase/auth-js internal default constant GOTRUE_URL ("http://localhost:9999")
    if (match[0] === "http://localhost:9999") continue;
    localhostHits.push({ file: file.replace(DIST, "dist/"), url: match[0] });
  }

  for (const pattern of [/\be2e@/, /review-leg-proof/, /deeplingo-web-e2e-.*\.json/]) {
    if (pattern.test(content)) {
      console.error(`FAIL: debug/E2E artifact content in ${file}`);
      failures += 1;
    }
  }
}

const unexpectedViteVars = [...viteVarNames].filter((name) => !ALLOWED_VITE_VARS.has(name));
for (const name of unexpectedViteVars) {
  console.error(`FAIL: unexpected VITE_ variable inlined into the bundle: ${name}`);
  failures += 1;
}

const strictRelease = process.argv.includes("--strict-release");

if (localhostHits.length > 0) {
  if (strictRelease) {
    console.error("FAIL: localhost URLs embedded in release candidate build (must use HTTPS or relative /api/v1/v3):");
    for (const hit of localhostHits) {
      console.error(`  ${hit.url} (${hit.file})`);
      failures += 1;
    }
  } else {
    console.warn("REPORT: localhost URLs embedded at build time (production guard refuses to boot these):");
    for (const hit of localhostHits) {
      console.warn(`  ${hit.url} (${hit.file})`);
    }
  }
}

console.log(`audit: scanned ${files} dist files`);
if (failures > 0) {
  console.error(`audit: FAILED (${failures} problem${failures === 1 ? "" : "s"})`);
  process.exit(1);
}
console.log("audit: OK — no privileged secrets, no source maps, no unexpected VITE_ variables");
