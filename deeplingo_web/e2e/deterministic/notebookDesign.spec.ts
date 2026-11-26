import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const API = "/api/v1/v3/learner/me";
const GROUP = "55555555-5555-4555-8555-555555555555";
const WORK = "77777777-7777-4777-8777-777777777777";
const HSK = "88888888-8888-4888-8888-888888888888";
const DAILY = "99999999-8888-4888-8888-888888888888";

type Entry = [text: string, gloss: string, reading?: string, traditional?: string];

// Five words are past their review date; the fifth is paused, so four are due.
function rows(language_code: string, idTail: string, entries: Entry[]) {
  return entries.map(([text, gloss, reading = null, traditional = null], index) => ({
    concept_id: `${index + 10}${idTail}`, language_code, text, gloss, reading, traditional, kind: "word",
    list: "saved", saved: true, save_source: "manual", explicit: true, status: index === 4 ? "suspended" : "active", rung: index % 5,
    level_label: language_code === "zh" ? "HSK 3" : "B1", above_level: false, note: index === 1 ? "Ghi nhớ cách dùng" : null, favorite: index === 0,
    next_review_at: index < 5 ? "2026-01-01T00:00:00Z" : null,
  }));
}

const english = rows("en", "666666-6666-4666-8666-666666666666", [
  ["reservation", "đặt chỗ"], ...["itinerary", "check in", "boarding pass", "layover", "sightseeing", "souvenir", "luggage", "round trip", "accommodation", "landing", "departure"]
    .map((text, index): Entry => [text, `meaning ${index + 1}`]),
]);
const chinese = rows("zh", "aaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", [
  ["学习", "học tập", "xué xí", "學習"], ["汉语", "tiếng Trung", "hàn yǔ", "漢語"], ["朋友", "bạn bè", "péng you"], ["老师", "giáo viên", "lǎo shī", "老師"],
  ["图书馆", "thư viện", "tú shū guǎn", "圖書館"], ["咖啡", "cà phê", "kā fēi"], ["电影", "phim", "diàn yǐng", "電影"], ["飞机", "máy bay", "fēi jī", "飛機"],
  ["火车", "tàu hỏa", "huǒ chē", "火車"], ["医院", "bệnh viện", "yī yuàn", "醫院"], ["天气", "thời tiết", "tiān qì", "天氣"], ["喜欢", "thích", "xǐ huan", "喜歡"],
  ["今天", "hôm nay", "jīn tiān"], ["明天", "ngày mai", "míng tiān"],
]);
const allWords = [...english, ...chinese];
const summary = (id: string, language_code: string, name: string, word_count: number) => ({ id, language_code, name, description: null, word_count, waiting_count: 0 });
const shelf = [
  summary(GROUP, "en", "Travel", english.length), summary(WORK, "en", "Work", 3),
  summary(HSK, "zh", "HSK 3", chinese.length), summary(DAILY, "zh", "Giao tiếp", 6),
];
const details: Record<string, { words: typeof allWords }> = { [GROUP]: { words: english }, [WORK]: { words: english.slice(0, 3) }, [HSK]: { words: chinese }, [DAILY]: { words: chinese.slice(0, 6) } };
const EXAMPLE = "我每天学习汉语。";
// One made-up character for every request to the stroke-data CDN: the screens only need a shape to draw.
const STROKES = {
  strokes: ["M 150 500 L 874 500 L 874 560 L 150 560 Z", "M 482 150 L 542 150 L 542 874 L 482 874 Z"],
  medians: [[[150, 530], [874, 530]], [[512, 874], [512, 150]]], radStrokes: [0],
};

const SHOTS = process.env.NOTEBOOK_SHOTS;
async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true, animations: "disabled" });
}
const noOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

const GRAMMAR_EXERCISE = { id: "zh.hsk1.le.1", grammar_key: "zh.hsk1.le", type: "choice", prompt: "我吃___饭。", options: ["了", "的", "得", "地"].map((text, n) => ({ id: `o${n}`, text })) };
const point = (key: string, title: string, topic_key: string, correct: number, wrong: number, lesson: unknown = null) => ({
  key, title, topic_key, lesson, exercise_count: 4, attempts: correct + wrong, correct_count: correct, incorrect_count: wrong,
  lesson_learned_at: null, last_correct_at: null });
const GRAMMAR = {
  language_code: "zh", support_language: "vi", levels: ["HSK1", "HSK2", "HSK3"], level: "HSK1",
  topics: [{ key: "particles", title: "Trợ từ" }, { key: "questions", title: "Câu hỏi" }],
  points: [
    point("zh.hsk1.le", "了 chỉ hành động đã xong", "particles", 4, 1, { summary: "了 đặt sau động từ để nói hành động đã hoàn thành.",
      rules: ["Động từ + 了 + tân ngữ", "Phủ định dùng 没 và bỏ 了"], examples: [{ text: "我吃了饭。", meaning: "Tôi ăn cơm rồi." }],
      mistakes: [{ wrong: "我没吃了饭。", right: "我没吃饭。", why: "没 không đi với 了." }] }),
    point("zh.hsk1.de", "的 nối định ngữ", "particles", 1, 2),
    point("zh.hsk1.ma", "吗 cuối câu hỏi có/không", "questions", 0, 0),
    point("zh.hsk1.ne", "呢 hỏi lại", "questions", 0, 0),
    point("zh.hsk1.shenme", "什么 hỏi cái gì", "questions", 0, 0),
  ],
  redo: [{ request_id: "r-1", grammar_key: "zh.hsk1.de", title: "的 nối định ngữ", level: "HSK1", reason: "Nói sai 的", created_at: "2026-11-14T00:00:00Z" }],
};
// The review engine builds each card's exercise on the server from the chosen types, taken in turn.
function dueCard(word: (typeof allWords)[number], type: string) {
  const exercise = type === "match"
    ? { type: "match", prompt: { text: word.text, reading: word.reading, meaning: word.gloss } }
    : type === "order"
      ? { type: "order", prompt: { kind: "characters", parts: [...word.text].reverse(), meaning: word.gloss } }
      : type === "writing"
        ? { type: "writing", prompt: { script: "strokes", characters: word.text, reading: word.reading, meaning: word.gloss } }
        : { type: "choice", prompt: { text: word.text, reading: word.reading, sentence: null, options: [word.gloss, "cà phê", "máy bay"].filter((item, index, all) => all.indexOf(item) === index) } };
  return { concept_id: word.concept_id, text: word.text, reading: word.reading, is_new: false, due_at: "2026-01-01T00:00:00Z", exercise };
}
let unexpected: string[] = [];
test.afterEach(() => { expect(unexpected).toEqual([]); });

async function fixture(page: Page) {
  const writes: string[] = [], bodies: unknown[] = [];
  unexpected = [];
  await page.addInitScript(() => {
    if (window.top !== window) return;
    localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({
      access_token: "e2e-dummy.header.token", token_type: "bearer", refresh_token: "dummy-refresh", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: "e2e-user", aud: "authenticated", role: "authenticated",
        email: "preview@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
    }));
  });
  await page.route("**/*", route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path.startsWith("/api/")) {
      const method = route.request().method();
      const id = path.split("/").at(-2) ?? "";
      // Picture lookups are a read that is sent as a POST.
      if (path === `${API}/words/images`) return json([]);
      if (method !== "GET") { writes.push(`${method} ${path.replace(API, "")}`); bodies.push(route.request().postDataJSON()); }
      if (path === `${API}/language-profile`) return json({ learning_language: "zh", support_language: "vi", declared_level: "HSK3", is_complete: true });
      if (path === `${API}/lists`) return json(shelf);
      if (path === `${API}/word-sets`) return json([{ key: "hsk-1", language_code: "zh", name: "HSK 1", word_count: 150 }, { key: "oxford-a1", language_code: "en", name: "Oxford A1", word_count: 900 }]);
      if (path === `${API}/grammar/zh`) return json(GRAMMAR);
      if (path === `${API}/grammar/zh/exercises`) return json({ language_code: "zh", grammar_key: url.searchParams.get("grammar_key"), exercises: [GRAMMAR_EXERCISE] });
      if (path === `${API}/review/decks`) return json({ decks: [{ language_code: "zh", due_count: 4, new_count: 0, total_count: chinese.length },
        { language_code: "en", due_count: 4, new_count: 0, total_count: english.length }] });
      if (path.startsWith(`${API}/review/`) && path.endsWith("/due")) {
        const chosen = (url.searchParams.getAll("concept_ids"));
        const words = (chosen.length ? allWords.filter(word => chosen.includes(word.concept_id)) : chinese.slice(0, 4)).slice(0, 5);
        const types = (url.searchParams.get("types") ?? "choice").split(",");
        return json({ language_code: path.split("/").at(-2), due_count: 4, new_count: 0, cards: words.map((word, index) => dueCard(word, types[index % types.length])) });
      }
      if (method === "POST" && path === `${API}/review/answers`) {
        const sent = route.request().postDataJSON();
        return json({ client_event_id: sent.client_event_id, concept_id: sent.concept_id, exercise_type: sent.exercise_type, outcome: "correct",
          correct: true, grade: "good", scheduled: true, next_review_at: "2026-12-01T00:00:00Z", expected: "", duplicate: false });
      }
      if (path === `${API}/dictionary/search`) return json([{ entry_id: "e1", headword: "harbour", level: null, senses: [{ sense_id: "s1", text: "a place for ships", part_of_speech: "noun", reading: null, example: null, meaning: "bến cảng" }] }]);
      if (method === "POST" && path === `${API}/words`) return json({ ...english[0], concept_id: "99999999-9999-4999-8999-999999999999", text: "harbour" });
      if (path === `${API}/words`) return json({ words: chinese, summary: null });
      if (path.endsWith("/examples")) {
        const zh = allWords.find(word => word.concept_id === id)?.language_code === "zh";
        return json({ concept_id: id, examples: zh ? [{ id: `example-${id}`, text: EXAMPLE, source_kind: "corpus", ai_generated: false, source_name: "Sentence collection", license_name: "CC BY", author: "A contributor", translation: "Mỗi ngày tôi học tiếng Trung." }] : [] });
      }
      if (path.endsWith("/pronunciation") && method === "GET") return json({ concept_id: id, latest: null });
      if (path.endsWith("/details")) {
        const word = allWords.find(item => item.concept_id === id);
        const zh = word?.language_code === "zh";
        return json({ concept_id: id, text: word?.text, traditional: word?.traditional, reading: word?.reading, level: word?.level_label,
          senses: [{ text: zh ? "to study" : "an arrangement to keep a place", reading: word?.reading, part_of_speech: zh ? "verb" : "noun" }],
          characters: zh ? [...(word?.text ?? "")].map(character => ({ character, reading: null, meaning: "thành phần" })) : [],
          compounds: zh ? [{ text: `${word?.text}班`, reading: null, meaning: "lớp" }] : [] });
      }
      if (method === "PUT" && path.endsWith("/personal")) return json({ ...allWords.find(word => word.concept_id === id), ...route.request().postDataJSON() });
      if (method === "POST" && path.endsWith("/memory-rating")) return json({ next_review_at: "2026-12-01T00:00:00Z" });
      if ((method === "PUT" || method === "DELETE") && path.includes("/lists/") && path.includes("/words/")) return route.fulfill({ status: 204 });
      const list = path.startsWith(`${API}/lists/`) ? shelf.find(item => path === `${API}/lists/${item.id}`) : undefined;
      if (list) return json({ ...list, ...details[list.id], waiting: [] });
      unexpected.push(`${method} ${path}`);
      return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    }
    if (url.origin === "https://cdn.jsdelivr.net") return route.fulfill({ contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(STROKES) });
    return url.origin === "http://localhost:5173" ? route.continue() : route.abort();
  });
  return { writes, bodies };
}

for (const width of [390, 1440]) {
  test(`the shelf shows the words due today and groups notebooks by language, ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { writes } = await fixture(page);
    await page.goto("/words/lists");
    await expect(page.getByRole("button", { name: /^Review now 4 words/ })).toBeEnabled();
    await expect(page.getByRole("heading", { name: /^中文/, level: 2 })).toBeVisible();
    await expect(page.getByRole("heading", { name: /^English/, level: 2 })).toBeVisible();
    // The language being learned comes first.
    await expect(page.locator(".shelf-group").first().getByRole("heading", { level: 2 })).toContainText("中文");
    await expect(page.locator(".shelf-group").first().locator(".notebook-tile")).toHaveCount(2);
    await expect(page.getByRole("link", { name: "HSK 3" }).first()).toHaveAttribute("href", `/words/lists/${HSK}`);
    // Owner decision 2026-11-14: no All words entry.
    await expect(page.getByRole("link", { name: /^All words/ })).toHaveCount(0);
    expect(await noOverflow(page)).toBe(true);
    expect(writes).toEqual([]);
    await shot(page, `shelf-${width}`);
  });
}

test("Review now opens the setup sheet on the due words and starts only those; each deck shows what is due", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { writes } = await fixture(page);
  await page.goto("/words/lists");
  await expect(page.getByRole("link", { name: "Review 中文: 4 due, 0 new" })).toHaveAttribute("href", "/review/zh");
  await expect(page.getByRole("link", { name: "Review English: 4 due, 0 new" })).toHaveAttribute("href", "/review/en");
  const due = page.getByRole("button", { name: /^Review now 4 words/ });
  await due.click();
  const sheet = page.getByRole("dialog", { name: "Review settings" });
  await expect(sheet.getByText("Words: 4")).toBeVisible();
  await expect(sheet.locator(".nb-chip")).toHaveCount(4);
  expect(writes).toEqual([]);
  await shot(page, "shelf-review-now-sheet");
  await sheet.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page).toHaveURL(/\/review\/zh\?types=choice&concepts=([0-9a-f-]+(%2C)?){4}&back=%2Fwords%2Flists$/);
  await expect(page.locator(".st-progress")).toContainText("1/4");
  expect(writes).toEqual([]);
});

for (const width of [390, 1440]) {
  test(`a notebook page lists its words and offers the study modes, ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { writes } = await fixture(page);
    await page.goto(`/words/lists/${HSK}`);
    const tiles = page.locator(".nbp-word");
    await expect(tiles).toHaveCount(chinese.length);
    await expect(tiles.first()).toContainText("学习【學習】");
    await expect(tiles.first()).toContainText("xué xí");
    const rail = page.locator(".nbp-study");
    await expect(rail.getByRole("button", { name: "Review" })).toBeEnabled();
    await expect(rail.getByRole("button", { name: "Pronunciation" })).toBeEnabled();
    await expect(rail.getByRole("link", { name: "Writing" })).toHaveAttribute("href", `/notebook/${HSK}/writing`);
    await expect(rail.getByRole("link", { name: "Flashcards" })).toHaveAttribute("href", `/notebook/${HSK}/flashcards`);
    expect(await noOverflow(page)).toBe(true);
    expect(writes).toEqual([]);
    await shot(page, `notebook-${width}`);
  });
}

test("the review setup sheet closes without writing and Start opens the notebook's review", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { writes } = await fixture(page);
  await page.goto(`/words/lists/${HSK}`);
  const review = page.locator(".nbp-study").getByRole("button", { name: "Review" });
  await review.click();
  const sheet = page.getByRole("dialog", { name: "Review settings" });
  await expect(sheet.getByText("Words: 5")).toBeVisible();
  await shot(page, "review-setup-sheet");
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(review).toBeFocused();
  expect(writes).toEqual([]);
  await review.click();
  await sheet.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/review/zh\\?types=choice&concepts=([0-9a-f-]+(%2C)?){5}&back=%2Fwords%2Flists%2F${HSK}$`));
  await expect(page.locator(".st-progress")).toContainText("1/5");
  expect(writes).toEqual([]);
});

test("a notebook can be searched without tone marks, sorted and shown without meanings", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixture(page);
  await page.goto(`/words/lists/${HSK}`);
  const tiles = page.locator(".nbp-word");
  await expect(tiles).toHaveCount(chinese.length);
  const search = page.getByRole("searchbox", { name: "Search words" });
  for (const typed of ["xue xi", "hoc tap"]) {
    await search.fill(typed);
    await expect(tiles).toHaveCount(1);
    await expect(tiles.first()).toContainText("学习");
  }
  await page.goto(`/words/lists/${GROUP}`);
  await expect(tiles).toHaveCount(english.length);
  // Writing is for Chinese and Japanese characters only: an English notebook has no Writing tile.
  await expect(page.locator(".nbp-study").getByRole("link", { name: "Writing" })).toHaveCount(0);
  await search.fill("dat cho");
  await expect(tiles).toHaveCount(1);
  await expect(tiles.first()).toContainText("reservation");
  await search.fill("");
  await expect(tiles).toHaveCount(english.length);
  await page.getByRole("button", { name: "Options", exact: true }).click();
  const options = page.getByRole("group", { name: "Options" });
  await options.getByRole("button", { name: "A-Z" }).click();
  await expect(tiles.first()).toContainText("accommodation");
  await options.getByRole("button", { name: "Oldest" }).click();
  await expect(tiles.first()).toContainText("departure");
  const meaning = tiles.first().locator(".nbp-word__mean");
  await expect(meaning).toBeVisible();
  await options.getByRole("button", { name: "Meaning", exact: true }).click();
  await expect(meaning).toBeHidden();
  await shot(page, "options-popover-open");
  await page.keyboard.press("Escape");
  await expect(options).toHaveCount(0);
  // Hiding is for self-testing: opening the word still shows it.
  await page.getByRole("button", { name: "Open departure" }).click();
  await expect(page.getByRole("dialog", { name: "departure" })).toContainText("meaning 11");
});

for (const width of [390, 1440]) {
  test(`a word's actions stay in its sheet until it is opened, ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { writes } = await fixture(page);
    await page.goto(`/words/lists/${GROUP}`);
    const open = page.getByRole("button", { name: "Open reservation" });
    const remove = page.getByRole("button", { name: "Remove from notebook" });
    await expect(open).toBeVisible();
    await expect(remove).toHaveCount(0);
    await open.click();
    const sheet = page.getByRole("dialog", { name: "reservation" });
    await expect(remove).toBeVisible();
    await sheet.getByRole("tab", { name: "Examples" }).click();
    await expect(page.getByText("This word has no example yet.")).toBeVisible();
    expect(await noOverflow(page)).toBe(true);
    expect(writes).toEqual([]);
    await shot(page, `word-sheet-${width}`);
    await sheet.getByRole("button", { name: "Close" }).click();
    await expect(remove).toHaveCount(0);
    await expect(open).toBeFocused();
    await open.click();
    await expect(sheet).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(open).toBeFocused();
  });
}

test("a Chinese word sheet shows its reading, characters and compounds", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { writes } = await fixture(page);
  await page.goto(`/words/lists/${HSK}`);
  await page.getByRole("button", { name: "Open 学习" }).click();
  const sheet = page.getByRole("dialog", { name: "学习" });
  await expect(sheet).toContainText("學習");
  await expect(sheet).toContainText("xué xí");
  await expect(sheet).toContainText("học tập");
  await expect(sheet).toContainText(EXAMPLE);
  await shot(page, "word-sheet-chinese");
  await sheet.getByRole("tab", { name: "Characters" }).click();
  await expect(sheet.locator(".nbp-reference li")).toHaveCount(2);
  await sheet.getByRole("tab", { name: "Compounds" }).click();
  await expect(sheet.locator(".nbp-reference li")).toHaveCount(1);
  expect(writes).toEqual([]);
});

test("selected words can be removed together after confirming, keeping them saved", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { writes } = await fixture(page);
  await page.goto(`/words/lists/${GROUP}`);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Select reservation" }).click();
  await page.getByRole("button", { name: "Select itinerary" }).click();
  await expect(page.getByText("2 selected")).toBeVisible();
  await expect(page.getByRole("button", { name: "Select reservation" })).toHaveAttribute("aria-pressed", "true");
  await shot(page, "edit-mode");
  const bar = page.getByRole("region", { name: "Select words" });
  await bar.getByRole("button", { name: "Delete" }).click();
  const confirm = page.getByRole("dialog", { name: "Remove 2 words from this notebook?" });
  await expect(confirm).toContainText("They stay in All words.");
  expect(writes).toEqual([]);
  await shot(page, "edit-mode-confirm-remove");
  await confirm.getByRole("button", { name: "Remove from notebook" }).click();
  await expect(bar).toHaveCount(0);
  await expect(confirm).toHaveCount(0);
  expect(writes).toEqual([`DELETE /lists/${GROUP}/words/${english[0].concept_id}`, `DELETE /lists/${GROUP}/words/${english[1].concept_id}`]);
});

test("a selected word moves to another notebook of the same language", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { writes } = await fixture(page);
  await page.goto(`/words/lists/${GROUP}`);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Select reservation" }).click();
  const bar = page.getByRole("region", { name: "Select words" });
  await bar.getByRole("button", { name: "Move" }).click();
  const dialog = page.getByRole("dialog", { name: "Move words" });
  await expect(dialog.getByRole("button", { name: /^Work/ })).toBeVisible();
  await expect(dialog.getByRole("button", { name: /^HSK 3/ })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: /^Travel/ })).toHaveCount(0);
  await dialog.getByRole("button", { name: /^Work/ }).click();
  expect(writes).toEqual([]);
  await shot(page, "move-dialog");
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(bar).toHaveCount(0);
  await expect(dialog).toHaveCount(0);
  expect(writes).toEqual([`PUT /lists/${WORK}/words/${english[0].concept_id}`, `DELETE /lists/${GROUP}/words/${english[0].concept_id}`]);
});

test("a word found in the dictionary is saved and put in this notebook", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { writes, bodies } = await fixture(page);
  await page.goto(`/words/lists/${GROUP}`);
  await page.getByRole("button", { name: "Add word", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add word" });
  await dialog.getByLabel("Add a word").fill("harbour");
  await dialog.getByLabel("Add a word").press("Enter");
  await dialog.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("“harbour” was added to this notebook.")).toBeVisible();
  await shot(page, "add-word-lookup");
  expect(writes.filter(write => !write.endsWith("/examples"))).toEqual(["POST /words", `PUT /lists/${GROUP}/words/99999999-9999-4999-8999-999999999999`]);
  expect(bodies[0]).toEqual({ source: "dictionary", language_code: "en", entry_id: "e1", sense_id: "s1" });
});

test("a flashcard flips, rates Memory one card later, and has no Can use rating", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { writes, bodies } = await fixture(page);
  await page.goto(`/words/lists/${HSK}`);
  await page.locator(".nbp-study").getByRole("link", { name: "Flashcards" }).click();
  await expect(page).toHaveURL(`/notebook/${HSK}/flashcards`);
  const card = page.getByTestId("flashcard");
  const position = page.locator(".st-corner-count").first();
  await expect(position).toHaveText(`1 / ${chinese.length}`);
  await expect(card.locator(".st-face").first()).toContainText("学习");
  expect(writes).toEqual([]);
  await shot(page, "flashcard-front");
  await card.click();
  await expect(card).toHaveClass(/flip/);
  const back = card.locator(".st-face-back");
  await expect(back).toContainText("học tập");
  await expect(back).toContainText("xué xí");
  await expect(back).toContainText(EXAMPLE);
  await shot(page, "flashcard-back");
  await expect(page.getByRole("group", { name: "Can use" })).toHaveCount(0);
  const id = chinese[0].concept_id;
  await page.getByRole("group", { name: "Memory" }).getByRole("button", { name: "Remembered" }).click();
  await expect(position).toHaveText(`2 / ${chinese.length}`);
  await expect(card.locator(".st-face").first()).toContainText("汉语");
  await expect(card).not.toHaveClass(/flip/);
  await expect(page.getByText("Remembered 1")).toBeVisible();
  // The rating waits until the next card is rated, so one step back can still take it back.
  expect(writes).toEqual([]);
  await shot(page, "flashcard-next-card");
  await page.getByRole("group", { name: "Memory" }).getByRole("button", { name: "Not yet" }).click();
  await expect(position).toHaveText(`3 / ${chinese.length}`);
  await expect.poll(() => writes).toEqual([`POST /words/${id}/memory-rating`]);
  expect(bodies).toEqual([{ rating: "remembered" }]);
});

test("on a phone the Tata bar shrinks while scrolling down and returns on the way up", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 500 });
  await fixture(page);
  await page.goto(`/words/lists/${HSK}`);
  await expect(page.locator(".nbp-word")).toHaveCount(chinese.length);
  const bar = page.locator(".agent-launcher");
  const width = async () => (await bar.boundingBox())!.width;
  expect(await width()).toBeGreaterThan(220);
  await page.evaluate(() => window.scrollTo(0, 400));
  await expect.poll(width).toBeLessThan(60);
  await expect(page.getByRole("link", { name: "Talk with Tata" })).toBeVisible();
  await shot(page, "tata-bar-compact");
  await page.evaluate(() => window.scrollTo(0, 100));
  await expect.poll(width).toBeGreaterThan(220);
});

test("a dialog's entrance motion is switched off when the device asks for reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixture(page);
  await page.goto(`/words/lists/${GROUP}`);
  const open = page.getByRole("button", { name: "Open reservation" });
  const duration = () => page.locator(".nb-modal").evaluate(element => parseFloat(getComputedStyle(element).animationDuration));
  await open.click();
  expect(await duration()).toBeGreaterThan(0.1);
  await page.keyboard.press("Escape");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open.click();
  expect(await duration()).toBeLessThan(0.001);
  await shot(page, "reduced-motion-word-sheet");
});

// For looking at the screens; the study flows themselves are covered by notebookStudy.test.tsx.
for (const width of [1440, 390]) {
  test(`the Chinese writing screen follows the Hanzii layout, ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { writes } = await fixture(page);
    await page.goto(`/notebook/${HSK}/writing`);
    await expect(page.getByRole("heading", { name: "Writing practice" })).toBeVisible();
    await expect(page.locator(".st-wr-writer svg")).toBeAttached();
    await expect(page.getByRole("alert")).toHaveCount(0);

    // The left card: the character with its reading and the Free writing switch, a square box, three round buttons.
    const main = page.locator(".st-wr-main");
    await expect(main.locator(".st-wr-char")).toHaveText("学");
    await expect(main.locator(".st-wr-reading")).toHaveText("xué");
    await expect(main.getByRole("button", { name: "Free writing" })).toBeVisible();
    const box = await page.locator(".st-wr-grid").boundingBox();
    expect(Math.abs(box!.width - box!.height)).toBeLessThan(1);
    await expect(main.locator(".st-wr-lines")).toBeAttached();
    await expect(main.locator(".st-wr-tools button")).toHaveCount(3);
    for (const name of ["Show stroke order", "Erase", "Show template"]) await expect(main.getByRole("button", { name })).toBeVisible();

    // The right column: a search box and one small tile per character, the current one highlighted.
    const characters = [...new Set(chinese.flatMap(word => [...word.text]))];
    const tiles = page.locator(".st-wr-list button");
    await expect(tiles).toHaveCount(characters.length);
    await expect(tiles.first()).toHaveAttribute("aria-current", "true");
    await expect(tiles.first()).toHaveText("xué学");
    const sideBox = await page.locator(".st-wr-side").boundingBox();
    const mainBox = await main.boundingBox();
    if (width >= 1000) expect(sideBox!.x).toBeGreaterThanOrEqual(mainBox!.x + mainBox!.width);
    else expect(sideBox!.y).toBeGreaterThanOrEqual(mainBox!.y + mainBox!.height - 1);
    await expect(page.getByRole("searchbox", { name: "Find a character" }).or(page.getByRole("textbox", { name: "Find a character" }))).toBeVisible();

    await tiles.nth(2).click();
    await expect(main.locator(".st-wr-char")).toHaveText(characters[2]);
    await expect(tiles.nth(2)).toHaveAttribute("aria-current", "true");
    expect(await noOverflow(page)).toBe(true);
    expect(writes).toEqual([]);
    await shot(page, `writing-${width}`);
  });

  test(`a review mixes the chosen types and the server grades each answer, ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { writes, bodies } = await fixture(page);
    await page.goto(`/words/lists/${HSK}`);
    await page.locator(".nbp-study").getByRole("button", { name: "Review" }).click();
    const sheet = page.getByRole("dialog", { name: "Review settings" });
    await sheet.getByRole("button", { name: "Select all" }).click();
    await sheet.getByRole("button", { name: "Order the sentence" }).click();
    await sheet.getByRole("button", { name: "Start", exact: true }).click();
    await expect(page).toHaveURL(/\/review\/zh\?types=choice%2Corder&/);
    await expect(page.locator(".st-progress")).toContainText("1/5");
    await page.locator(".st-ans-col").getByRole("button", { name: "học tập" }).click();
    await expect(page.locator(".st-fb.good")).toContainText("Correct");
    expect(await noOverflow(page)).toBe(true);
    await shot(page, `review-choice-${width}`);
    await page.getByRole("button", { name: "Continue" }).click();
    // Multiple choice asks the meaning and, by listening, the word; Order comes third in turn.
    await expect(page.locator(".st-progress")).toContainText("2/5");
    await page.locator(".st-ans-col").getByRole("button", { name: "tiếng Trung" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Put the characters in order")).toBeVisible();
    for (const part of ["朋", "友"]) await page.getByTestId("order-bank").getByRole("button", { name: part }).click();
    await page.getByRole("button", { name: "Check" }).click();
    await expect(page.locator(".st-fb.good")).toBeVisible();
    await shot(page, `review-order-${width}`);
    expect(writes).toEqual(["POST /review/answers", "POST /review/answers", "POST /review/answers"]);
    expect(bodies[0]).toMatchObject({ concept_id: chinese[0].concept_id, exercise_type: "choice", answer: { option: "học tập" } });
    expect(bodies[1]).toMatchObject({ concept_id: chinese[1].concept_id, exercise_type: "choice", answer: { option: "tiếng Trung" } });
    expect(bodies[2]).toMatchObject({ concept_id: chinese[2].concept_id, exercise_type: "order", answer: { text: "朋友" } });
  });
}
for (const width of [1440, 390]) {
  test(`grammar opens inside the notebook area and practises there, ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await fixture(page);
    await page.goto("/words/lists");
    await page.getByRole("group", { name: "Notebook area" }).getByRole("button", { name: "Grammar" }).click();
    await expect(page.getByRole("heading", { name: "Trợ từ" })).toBeVisible();
    await expect(page).toHaveURL(/\/words\/lists$/);
    expect(await noOverflow(page)).toBe(true);
    await shot(page, `grammar-${width}`);
    await page.getByRole("button", { name: /了 chỉ hành động đã xong/ }).click();
    await expect(page.getByRole("heading", { name: "了 chỉ hành động đã xong" })).toBeVisible();
    await expect(page.getByText("我吃了饭。")).toBeVisible();
    expect(await noOverflow(page)).toBe(true);
    await shot(page, `grammar-lesson-${width}`);
    await page.getByRole("button", { name: "Practise this point" }).click();
    await expect(page.getByText("我吃___饭。")).toBeVisible();
    await expect(page).toHaveURL(/\/words\/lists$/);
    await page.getByRole("button", { name: "Back to grammar points" }).click();
    await expect(page.getByRole("region", { name: "To redo" })).toContainText("Nói sai 的");
    await shot(page, `grammar-practice-${width}`);
  });
}
