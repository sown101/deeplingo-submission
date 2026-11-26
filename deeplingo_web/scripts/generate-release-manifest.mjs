// Writes release/manifest.json from build and test evidence. The report is not committed: it names the
// commit it was produced at, so committing it would change that commit.
//   node scripts/generate-release-manifest.mjs [--ai-limit-evidence <file>]
// Exit code 0 only when every check is derived as passed; 1 when the candidate is blocked.
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { buildManifest } from "./release_lib.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));

function gitInfo(cwd) {
  const git = (args) => spawnSync("git", args, { cwd, encoding: "utf8" });
  const head = git(["rev-parse", "HEAD"]);
  if (head.status !== 0) return { head_commit: "unknown", dirty_in_web: null };
  const dirty = git(["status", "--porcelain", "--", "."]).stdout.split("\n").map((l) => l.trim()).filter(Boolean);
  return { head_commit: head.stdout.trim(), dirty_in_web: dirty.length > 0, dirty_files_in_web: dirty };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
  const at = args.indexOf("--ai-limit-evidence");
  const { manifest, blockers } = buildManifest({ root, git: gitInfo(root), aiLimitEvidence: at >= 0 ? args[at + 1] : undefined });
  mkdirSync(join(root, "release"), { recursive: true });
  const out = join(root, "release", "manifest.json");
  writeFileSync(out, JSON.stringify(manifest, null, 2) + "\n");
  console.log(`${manifest.release_candidate_id}: ${manifest.status} (live: ${manifest.live.status}) -> ${out}`);
  for (const b of blockers) console.log(`  blocked: ${b}`);
  process.exitCode = blockers.length ? 1 : 0;
}
