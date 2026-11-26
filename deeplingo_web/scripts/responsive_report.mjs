// Builds test-results/responsive/index.html: one section per screen, one row per viewport size, one cell per
// browser, with a badge for each finding. Run after `npm run test:e2e:responsive`.
import { readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const ROOT = "test-results/responsive";
if (!existsSync(ROOT)) {
  console.error(`No results in ${ROOT}. Run npm run test:e2e:responsive first.`);
  process.exit(1);
}

const results = [];
for (const browser of readdirSync(ROOT, { withFileTypes: true }).filter((entry) => entry.isDirectory())) {
  for (const file of readdirSync(join(ROOT, browser.name)).filter((name) => name.endsWith(".json"))) {
    results.push({ ...JSON.parse(readFileSync(join(ROOT, browser.name, file), "utf8")), png: `${browser.name}/${file.replace(/\.json$/, ".png")}` });
  }
}

const browsers = [...new Set(results.map((r) => r.browser))].sort();
const screens = [...new Set(results.map((r) => r.screen))];
const sizes = [...new Set(results.map((r) => `${r.width}x${r.height}`))].sort((a, b) => parseInt(a) - parseInt(b) || parseInt(a.split("x")[1]) - parseInt(b.split("x")[1]));
const find = (screen, size, browser) => results.find((r) => r.screen === screen && `${r.width}x${r.height}` === size && r.browser === browser);
const esc = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

let failing = 0;
let notes = 0;
const sections = screens.map((screen) => {
  const rows = sizes.map((size) => {
    const cells = browsers.map((browser) => {
      const r = find(screen, size, browser);
      if (!r) return `<td class="missing">no run</td>`;
      const bad = r.overflowPx > 1;
      if (bad) failing += 1;
      const extra = [...(r.sticksOut.length ? [`sticks out: ${r.sticksOut.join(", ")}`] : []), ...(r.underFixedBar.length ? [`under a fixed bar: ${r.underFixedBar.join(", ")}`] : [])];
      if (extra.length) notes += 1;
      const badges = [bad ? `<b class="bad">scrolls sideways ${r.overflowPx}px</b>` : "", extra.length ? `<i class="note" title="${esc(extra.join(" | "))}">${extra.length} note(s)</i>` : ""].join(" ");
      return `<td><a href="${r.png}" target="_blank"><img loading="lazy" src="${r.png}" width="${Math.min(200, Math.round(r.width / 3))}"></a><div>${badges}</div></td>`;
    });
    return `<tr><th>${size}</th>${cells.join("")}</tr>`;
  });
  return `<section id="${screen}"><h2>${screen}</h2><table><tr><th></th>${browsers.map((b) => `<th>${b}</th>`).join("")}</tr>${rows.join("")}</table></section>`;
});

const nav = screens.map((s) => `<a href="#${s}">${s}</a>`).join(" · ");
writeFileSync(
  join(ROOT, "index.html"),
  `<!doctype html><meta charset="utf-8"><title>Responsive screenshots</title>
<style>body{font:14px system-ui;background:#111;color:#eee;margin:16px}a{color:#7fddd3}table{border-collapse:collapse;margin-bottom:28px}td,th{border:1px solid #333;padding:6px;vertical-align:top;text-align:left}img{display:block;border:1px solid #444}.bad{color:#ff6961}.note{color:#ff9230;font-style:normal}.missing{color:#888}</style>
<h1>Responsive screenshots</h1><p>${results.length} screenshots · ${failing} scroll sideways · ${notes} with notes (hover a note for details)</p><p>${nav}</p>${sections.join("")}`,
);
console.log(`${results.length} screenshots, ${failing} scroll sideways, ${notes} with notes -> ${ROOT}/index.html`);
