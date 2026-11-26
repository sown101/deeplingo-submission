import { describe, expect, it } from "vitest";
import { LABEL_TEXT } from "../features/coverage/coverageModels";
import { BAND_COPY } from "../features/speaking/SpeakingFeedback";
import { RUNG_LABELS } from "../features/words/wordsModels";
import { VI } from "./vi";

// FR-6.1: English text is the key. A static string wrapped in <T> or t("…") without a Vietnamese entry would silently
// show English to a Vietnamese learner, and a Vietnamese string typed into a screen would show Vietnamese to everyone.
const RAW = import.meta.glob("../**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

// The privacy notice is a Vietnamese legal text awaiting legal review (PRD Q8); it is not translated.
const SKIPPED = new Set(["features/privacy/PrivacyScreen.tsx"]);
// Developer-facing configuration message, a URL example and example words in the language being learned: not interface text.
const NOT_INTERFACE_TEXT = new Set([
  ". In production builds the API origin must use HTTPS (same-origin",
  "is also supported) and must not point at development infrastructure.",
  "https://www.youtube.com/watch?v=…",
  "airport\nrely on\ngive up, to stop trying",
]);
const VIETNAMESE_LETTER = /[ăâđêôơưĂÂĐÊÔƠƯàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]/;

const files = Object.entries(RAW)
  .map(([path, text]) => [path.replace(/^\.\.\//, "").replace(/^\.\//, "i18n/"), text] as const)
  .filter(([path]) => !/\.test\.tsx?$/.test(path) && !/^(i18n|test|contracts)\//.test(path) && !SKIPPED.has(path));

function staticKeys(text: string): string[] {
  const keys: string[] = [];
  for (const match of text.matchAll(/<T\b[^>]*>([\s\S]*?)<\/T>/g)) {
    const body = match[1].trim();
    const literal = body.match(/^\{\s*"((?:[^"\\]|\\.)*)"\s*\}$/);
    if (literal) keys.push(JSON.parse(`"${literal[1]}"`) as string);
    else if (!body.includes("{") && !body.includes("<")) keys.push(body.replace(/\s+/g, " "));
  }
  // Constant tables such as nav items and tabs: { label: "Home" } is shown through t() where it is displayed.
  for (const match of text.matchAll(/\blabel:\s*"((?:[^"\\]|\\.)*)"/g)) keys.push(JSON.parse(`"${match[1]}"`) as string);
  for (const match of text.matchAll(/\b(?:t|tr)\(\s*"((?:[^"\\]|\\.)*)"/g)) keys.push(JSON.parse(`"${match[1]}"`) as string);
  return keys;
}

describe("Vietnamese catalog coverage (FR-6.1)", () => {
  it("scans the screens", () => {
    expect(files.length).toBeGreaterThan(40);
  });

  it("has a Vietnamese entry for every static string wrapped in <T> or t()", () => {
    const missing: string[] = [];
    for (const [path, text] of files) {
      for (const key of staticKeys(text)) {
        if (!(key in VI) && !NOT_INTERFACE_TEXT.has(key)) missing.push(`${path}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("has a Vietnamese entry for the exported label tables that screens translate where they show them", () => {
    const labels = [...Object.values(LABEL_TEXT), ...RUNG_LABELS, ...Object.values(BAND_COPY).flatMap(band => [band.title, band.hint])];
    expect(labels.filter(label => !(label in VI))).toEqual([]);
  });

  it("keeps Vietnamese out of the source text of screens (it belongs in the catalog)", () => {
    const hardCoded: string[] = [];
    for (const [path, text] of files) {
      text.split(/\r?\n/).forEach((line, index) => {
        // The Chinese coverage warning is the owner's exact Vietnamese wording (PRD FR-1.4).
        if (VIETNAMESE_LETTER.test(line) && !line.trim().startsWith("//") && !line.includes("tiếng Trung chưa được hiệu chuẩn")) {
          hardCoded.push(`${path}:${index + 1}`);
        }
      });
    }
    expect(hardCoded).toEqual([]);
  });
});
