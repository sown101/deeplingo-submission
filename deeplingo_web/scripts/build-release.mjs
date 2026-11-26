// Builds dist/ and records what was actually used: the VITE_ configuration vite resolves for
// production (env files plus process environment), the hashed build inputs and the hashed output.
// The record is local evidence (release/, untracked); release candidate reports compare against it.
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadEnv } from "vite";
import { BUILD_INPUTS, SCHEMA, configFromEnv, distFingerprint, fingerprint } from "./release_lib.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const run = (script, args) => {
  const r = spawnSync(process.execPath, [join(root, "node_modules", script), ...args], { cwd: root, stdio: "inherit" });
  if (r.status !== 0) process.exit(r.status ?? 1);
};
const version = (pkg) => JSON.parse(readFileSync(join(root, "node_modules", pkg, "package.json"), "utf8")).version;

const env = loadEnv("production", root, "VITE_");
const before = fingerprint(root, BUILD_INPUTS);
run("typescript/bin/tsc", ["-b"]);
run("vite/bin/vite.js", ["build"]);
const after = fingerprint(root, BUILD_INPUTS);
if (after.sha256 !== before.sha256) { console.error("build inputs changed while building; record not written"); process.exit(1); }

let head = "unknown";
let dirty = null;
const git = (args) => spawnSync("git", args, { cwd: root, encoding: "utf8" });
const h = git(["rev-parse", "HEAD"]);
if (h.status === 0) {
  head = h.stdout.trim();
  dirty = git(["status", "--porcelain", "--", "."]).stdout.trim().length > 0;
}

mkdirSync(join(root, "release"), { recursive: true });
const record = {
  schema: SCHEMA,
  built_at: new Date().toISOString(),
  build_inputs: after,
  dist: distFingerprint(root),
  config: configFromEnv(env),
  toolchain: { node: process.version, vite: version("vite"), typescript: version("typescript"), react: version("react") },
  git: { head_commit: head, dirty_in_web: dirty },
};
writeFileSync(join(root, "release", "build-record.json"), JSON.stringify(record, null, 2) + "\n");
console.log(`build record written: inputs ${after.sha256.slice(0, 12)}, dist ${record.dist.sha256.slice(0, 12)}`);
