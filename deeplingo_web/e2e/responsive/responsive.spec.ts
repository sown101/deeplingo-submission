import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { API, LIB_ID, json, mockBackend, seedSession } from "./support";

// Responsive screenshot suite.
//
// Every screen is opened at ten viewport sizes (portrait and landscape of 320, 390, 768, 1024 and 1440 wide)
// in each browser project of playwright.responsive.config.ts (Chromium, WebKit, Firefox). Each run saves a
// viewport screenshot and a small JSON file; `npm run report:responsive` builds a gallery from them.
//
// Hard assertion: the page never scrolls horizontally. Informational findings (not failures): elements that
// stick out of the viewport and tappable elements under a fixed bar. Review them in the gallery.
//
// Every backend request is answered from local fixtures and external hosts are aborted: no real backend,
// Supabase, YouTube or AI provider is used.

type Screen = { name: string; path: string; signedIn: boolean };

const SCREENS: Screen[] = [
  { name: "landing", path: "/landing", signedIn: false },
  { name: "signin", path: "/signin", signedIn: false },
  { name: "forgot-password", path: "/forgot-password", signedIn: false },
  { name: "reset-password", path: "/reset-password", signedIn: false },
  { name: "privacy", path: "/privacy", signedIn: false },
  { name: "home", path: "/home", signedIn: true },
  { name: "watch", path: `/library/videos/${LIB_ID}/watch`, signedIn: true },
  { name: "notebook", path: "/words/lists", signedIn: true },
  { name: "level-words", path: "/words?level=0", signedIn: true },
  { name: "word-set", path: "/words/sets/all", signedIn: true },
  { name: "flashcards", path: "/notebook/all/flashcards", signedIn: true },
  { name: "writing", path: "/notebook/all/writing", signedIn: true },
  { name: "quick-review", path: "/review/quick", signedIn: true },
  { name: "progress", path: "/progress", signedIn: true },
  { name: "account", path: "/account", signedIn: true },
  { name: "agent", path: "/agent", signedIn: true },
  { name: "agent-voice", path: "/agent?mode=voice", signedIn: true },
];

// [width, height]: portrait and landscape of each width.
const VIEWPORTS: [number, number][] = [
  [320, 640], [640, 320],
  [390, 844], [844, 390],
  [768, 1024], [1024, 768],
  [1024, 1366], [1366, 1024],
  [1440, 900], [900, 1440],
];

const OUT = "test-results/responsive";

async function prepare(page: Page, signedIn: boolean): Promise<void> {
  if (signedIn) {
    await seedSession(page);
    await mockBackend(page);
    // Progress reads one endpoint; give it data so the chart layout is visible.
    await page.route(`**${API}/learner/me/progress**`, (route) =>
      json(route, {
        language: null, languages: ["en"], utc_offset_minutes: 0, window_days: 365,
        streak: { current: 3, longest: 5, active_days: 3 },
        heatmap: [{ date: "2026-11-08", count: 2 }, { date: "2026-11-09", count: 1 }, { date: "2026-11-10", count: 4 }],
        cards: [{ language_code: "en", total: 6, due: 2, new: 2, learning: 1, review: 2, relearning: 1 }],
        accuracy: [{ kind: "choice", attempts: 4, correct: 3, accuracy: 75 }],
        pronunciation: [
          { date: "2026-11-05", attempts: 2, score: 77 },
          { date: "2026-11-08", attempts: 1, score: 82 },
          { date: "2026-11-10", attempts: 3, score: 88 },
        ],
        grammar: { learned: 2, done_correctly: 1 }, regions_completed: 1, speaking: { sessions: 2, minutes: 6 },
      }),
    );
  } else {
    await page.route("**/*", (route) => {
      const host = new URL(route.request().url()).hostname;
      return host === "localhost" || host === "127.0.0.1" ? route.continue() : route.abort();
    });
  }
}

type Findings = { overflowPx: number; sticksOut: string[]; underFixedBar: string[]; stuckUnderFixedBar?: string[] };

async function measure(page: Page): Promise<Findings> {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const label = (el: Element) => `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.split(" ")[0] : ""}`;
    const scrollsX = (el: Element | null) => {
      for (let a = el; a && a !== document.body; a = a.parentElement) {
        if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(a).overflowX)) return true;
      }
      return false;
    };
    const sticksOut: string[] = [];
    document.body.querySelectorAll("*").forEach((el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      if (r.width === 0 || r.height === 0 || s.visibility === "hidden" || s.display === "none" || s.position === "fixed") return;
      if ((r.right > vw + 1 || r.left < -1) && !scrollsX(el.parentElement)) sticksOut.push(label(el));
    });
    const fixed = [...document.body.querySelectorAll("*")].filter((el) => {
      const r = el.getBoundingClientRect();
      return getComputedStyle(el).position === "fixed" && r.width > 40 && r.height > 20 && r.bottom > 0 && r.top < window.innerHeight;
    });
    const underFixedBar: string[] = [];
    document.body.querySelectorAll("button, a[href], input, select, textarea, [role=button]").forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0 || r.bottom < 0 || r.top > window.innerHeight) return;
      if (fixed.some((f) => f.contains(el))) return;
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const top = document.elementFromPoint(cx, cy);
      if (top && top !== el && !el.contains(top) && fixed.some((f) => f.contains(top))) underFixedBar.push(label(el) + ":" + (el.textContent ?? "").trim().slice(0, 24));
    });
    return {
      overflowPx: document.documentElement.scrollWidth - vw,
      sticksOut: [...new Set(sticksOut)].slice(0, 8),
      underFixedBar: [...new Set(underFixedBar)].slice(0, 8),
    };
  });
}

for (const screen of SCREENS) {
  for (const [width, height] of VIEWPORTS) {
    test(`${screen.name} ${width}x${height}`, async ({ page, browserName }) => {
      await page.setViewportSize({ width, height });
      await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
      await prepare(page, screen.signedIn);
      await page.goto(screen.path);
      await page.waitForLoadState("load");
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(1200);

      const dir = `${OUT}/${browserName}`;
      mkdirSync(dir, { recursive: true });
      const base = `${screen.name}__${width}x${height}`;
      await page.screenshot({ path: `${dir}/${base}.png` });
      const findings = await measure(page);
      // A control under a bar at the top is fine when scrolling reveals it, and one under the top bar at the end
      // is revealed by scrolling back: only a control covered at both ends of the page can never be tapped.
      await page.evaluate(() => {
        window.scrollTo(0, document.documentElement.scrollHeight);
        document.querySelectorAll("*").forEach((el) => {
          if (el.scrollHeight > el.clientHeight + 4 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) el.scrollTop = el.scrollHeight;
        });
      });
      await page.waitForTimeout(150);
      findings.stuckUnderFixedBar = (await measure(page)).underFixedBar.filter((control) => findings.underFixedBar.includes(control));
      writeFileSync(`${dir}/${base}.json`, JSON.stringify({ screen: screen.name, path: screen.path, width, height, browser: browserName, ...findings }));

      expect(findings.overflowPx, `${screen.name} scrolls horizontally by ${findings.overflowPx}px (${findings.sticksOut.join(", ")})`).toBeLessThanOrEqual(1);
      expect(findings.stuckUnderFixedBar, `${screen.name}: controls stay under a fixed bar at the end of the page`).toEqual([]);
    });
  }
}
