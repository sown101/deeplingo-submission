// WEB-8C bundle measurement — reproducible before/after numbers.
//
//   node scripts/measure-bundle.mjs [--budget <gzipKiB>]
//
// Prints per-asset raw/gzip sizes for dist/, identifies the INITIAL entry
// chunk from index.html (script + modulepreload), and prints the standard
// comparison table. With --budget, exits non-zero when the initial JS gzip
// exceeds the budget (used as the CI performance regression guard).

import { readdirSync, readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join, extname, basename } from "node:path";

const DIST = new URL("../dist/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

const budgetArg = process.argv.indexOf("--budget");
const budgetKiB = budgetArg >= 0 ? Number(process.argv[budgetArg + 1]) : null;

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const files = walk(DIST)
  .map((f) => f.replaceAll("\\", "/"))
  .filter((f) => [".js", ".css"].includes(extname(f)));

const assets = files.map((file) => {
  const raw = readFileSync(file);
  return {
    name: file.replace(DIST.replaceAll("\\", "/"), "dist/"),
    kind: extname(file) === ".js" ? "js" : "css",
    raw: raw.length,
    gzip: gzipSync(raw).length,
  };
});

const html = readFileSync(join(DIST, "index.html"), "utf8");
const entryRefs = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+\.js)"/g)].map((m) => m[1]);
const entryNames = new Set(entryRefs.map((ref) => `dist${ref}`));

const initialJs = assets.filter((a) => a.kind === "js" && entryNames.has(a.name));
const asyncJs = assets.filter((a) => a.kind === "js" && !entryNames.has(a.name));
const css = assets.filter((a) => a.kind === "css");
const sum = (list, key) => list.reduce((acc, a) => acc + a[key], 0);

console.log("=== dist assets ===");
for (const a of [...initialJs, ...asyncJs, ...css].sort((x, y) => y.raw - x.raw)) {
  const tag = entryNames.has(a.name) ? " [initial]" : a.kind === "js" ? " [async]" : "";
  console.log(
    `${a.name}  raw ${(a.raw / 1024).toFixed(1)} KiB  gzip ${(a.gzip / 1024).toFixed(1)} KiB${tag}`,
  );
}

const initialRaw = sum(initialJs, "raw");
const initialGzip = sum(initialJs, "gzip");
const totalJsRaw = sum(assets.filter((a) => a.kind === "js"), "raw");
const totalJsGzip = sum(assets.filter((a) => a.kind === "js"), "gzip");
const cssRaw = sum(css, "raw");
const cssGzip = sum(css, "gzip");
const jsChunks = assets.filter((a) => a.kind === "js").length;
const largest = [...initialJs, ...asyncJs].sort((a, b) => b.raw - a.raw)[0];

console.log("\n=== summary ===");
console.log(JSON.stringify(
  {
    initial_js_raw_kib: +(initialRaw / 1024).toFixed(1),
    initial_js_gzip_kib: +(initialGzip / 1024).toFixed(1),
    total_js_raw_kib: +(totalJsRaw / 1024).toFixed(1),
    total_js_gzip_kib: +(totalJsGzip / 1024).toFixed(1),
    js_chunk_count: jsChunks,
    largest_chunk: { name: basename(largest?.name ?? ""), raw_kib: +(largest.raw / 1024).toFixed(1) },
    css_raw_kib: +(cssRaw / 1024).toFixed(1),
    css_gzip_kib: +(cssGzip / 1024).toFixed(1),
  },
  null,
  1,
));

if (budgetKiB !== null) {
  if (initialJs.length === 0) {
    console.error("bundle budget: FAILED — no initial JS entry found in dist/index.html");
    process.exit(1);
  }
  if (initialGzip / 1024 > budgetKiB) {
    console.error(
      `bundle budget: FAILED — initial JS gzip ${(initialGzip / 1024).toFixed(1)} KiB exceeds budget ${budgetKiB} KiB`,
    );
    process.exit(1);
  }
  console.log(
    `bundle budget: OK — initial JS gzip ${(initialGzip / 1024).toFixed(1)} KiB within budget ${budgetKiB} KiB`,
  );
}
