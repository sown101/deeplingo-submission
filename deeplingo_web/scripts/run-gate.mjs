// Runs one verification command and writes evidence for it: the exit code, the runner's own counts and
// hashes of the inputs (and dist, for gates that read it) at the time of the run.
//   node scripts/run-gate.mjs <gate> -- <command...>
// With no arguments after the gate name, the standard command for that gate is used.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { DIST_GATES, REQUIRED_GATES, VERIFICATION_INPUTS, distFingerprint, fingerprint, parseCounts } from "./release_lib.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));

export const STANDARD = {
  typecheck: "npm run typecheck",
  unit: "npm run test",
  node_helpers: 'node --test "scripts/*.test.mjs"',
  e2e_deterministic: "npm run test:e2e:deterministic",
  bundle: "npm run check:bundle",
  audit: "npm run audit:release",
};

export function runGate(gate, command, cwd = root, { echo = true } = {}) {
  if (!REQUIRED_GATES.includes(gate)) throw new Error(`Unknown gate: ${gate}`);
  const before = fingerprint(cwd, VERIFICATION_INPUTS).sha256;
  const started = new Date();
  const result = spawnSync(command, { cwd, shell: true, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  if (echo) process.stdout.write(output);
  const after = fingerprint(cwd, VERIFICATION_INPUTS).sha256;
  // A run that raced with an edit proves nothing about either version.
  const exit = after !== before ? 1 : (result.status ?? 1);
  const evidence = {
    gate,
    command,
    exit_code: exit,
    started_at: started.toISOString(),
    finished_at: new Date().toISOString(),
    verification_inputs: after,
    dist_sha256: DIST_GATES.includes(gate) ? distFingerprint(cwd)?.sha256 ?? null : undefined,
    counts: parseCounts(output),
    output_sha256: createHash("sha256").update(output).digest("hex"),
    ...(after !== before ? { note: "inputs changed during the run" } : {}),
  };
  mkdirSync(join(cwd, "release", "evidence"), { recursive: true });
  writeFileSync(join(cwd, "release", "evidence", `${gate}.json`), JSON.stringify(evidence, null, 2) + "\n");
  return evidence;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [gate, sep, ...rest] = process.argv.slice(2);
  const command = sep === "--" && rest.length ? rest.join(" ") : STANDARD[gate];
  if (!command) { console.error("usage: run-gate.mjs <gate> [-- command...]"); process.exit(2); }
  const evidence = runGate(gate, command);
  console.log(`gate ${gate}: exit ${evidence.exit_code}, counts ${JSON.stringify(evidence.counts)}`);
  process.exitCode = evidence.exit_code === 0 ? 0 : 1;
}
