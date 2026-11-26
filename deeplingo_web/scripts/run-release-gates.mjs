// Runs every required gate in turn and records evidence for each, continuing after a failure so the
// report shows the full picture. Build first: npm run build:release.
import { REQUIRED_GATES } from "./release_lib.mjs";
import { STANDARD, runGate } from "./run-gate.mjs";

let failed = 0;
for (const gate of REQUIRED_GATES) {
  const evidence = runGate(gate, STANDARD[gate]);
  console.log(`gate ${gate}: exit ${evidence.exit_code}, counts ${JSON.stringify(evidence.counts)}`);
  if (evidence.exit_code !== 0) failed += 1;
}
process.exitCode = failed ? 1 : 0;
