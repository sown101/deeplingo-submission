import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { emptyReport, parseListSummaries } from "./listsModels";
import type { MyWord } from "./wordsModels";
import { WordListsScreen } from "./WordListsScreen";
import { WordSetScreen } from "./WordSetScreen";

vi.mock("../notebookStudy/ReviewSetupSheet", () => ({
  ReviewSetupSheet: (props: { scope: string; words: { text: string }[]; preselected?: string[]; onClose: () => void }) => (
    <div role="dialog" aria-label="review setup">
      <span>{props.scope}|{props.words.map(word => word.text).join(",")}|{props.preselected?.join(",")}</span>
      <button type="button" onClick={props.onClose}>close review</button>
    </div>
  ),
}));

const raw = (id: string, name: string, language_code: string, word_count = 3) => ({ id, language_code, name, description: null, word_count, waiting_count: 0 });
const ZH = raw("zh-1", "HSK notes", "zh");
const EN_B = raw("en-b", "Banana", "en");
const EN_A = raw("en-a", "Apple", "en");

function word(id: string, overrides: Partial<MyWord> = {}): MyWord {
  return {
    conceptId: id, languageCode: "en", text: id, kind: "word", gloss: null, list: "saved", saved: true, saveSource: "manual",
    addedAt: null, nextReviewAt: null, status: "active", explicit: true, reading: null, traditional: null, note: null,
    favorite: false, priority: 0, levelLabel: null, rung: 0, aboveLevel: false, ...overrides,
  };
}

function shelfContainer(overrides: { lists?: object; words?: MyWord[]; sets?: unknown[]; wordsFail?: boolean } = {}) {
  return {
    onboarding: { loadProfile: vi.fn(async () => ({ learning_language: "en", support_language: "vi" })) },
    lists: {
      list: vi.fn(async () => parseListSummaries([EN_B, ZH, EN_A])),
      create: vi.fn(async () => parseListSummaries([EN_A])[0]),
      remove: vi.fn(async () => undefined),
      ...overrides.lists,
    },
    words: {
      list: vi.fn(async () => {
        if (overrides.wordsFail) throw new ApiError("network", null, {});
        return { words: overrides.words ?? [], summary: null };
      }),
    },
    notebook: { sets: vi.fn(async () => overrides.sets ?? [{ key: "hsk1", languageCode: "zh", name: "HSK 1", wordCount: 504 }, { key: "a1", languageCode: "en", name: "A1", wordCount: 600 }]) },
    review: { decks: vi.fn(async () => [{ languageCode: "en", dueCount: 1, newCount: 2, totalCount: 3 }]) },
  };
}

function Where() {
  const location = useLocation();
  return <p>at {location.pathname}{location.search}</p>;
}

function mount(container: unknown, path = "/words/lists", extra: ReactNode = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={client}>
        <ContainerProvider container={container as AppContainer}>
          <Routes>
            <Route path="/words/lists" element={<WordListsScreen />} />
            <Route path="/words/sets/:setKey" element={<WordSetScreen />} />
            <Route path="*" element={<Where />} />
          </Routes>
          {extra}
        </ContainerProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

const past = "2026-01-01T00:00:00Z";

describe("Notebook shelf", () => {
  it("shows the learning language first and each notebook, with no All words entry", async () => {
    mount(shelfContainer({ words: [word("a"), word("b"), word("c", { saved: false })] }));
    const headings = (await screen.findAllByRole("heading", { level: 2 })).map(heading => heading.textContent);
    await screen.findByText("Apple");
    expect((await screen.findAllByRole("heading", { level: 2 })).map(heading => heading.textContent).filter(text => text === "English" || text?.includes("·"))).toEqual(["English", "中文 · Chinese"]);
    // Owner decision 2026-11-14: the All words page is not needed.
    expect(headings).not.toContain("Personal");
    expect(screen.queryByRole("link", { name: /All words/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /HSK notes/ })).toHaveAttribute("href", "/words/lists/zh-1");
    expect(document.querySelectorAll(".notebook-tile")).toHaveLength(3);
  });

  it("counts saved words by level and opens a level from its bar", async () => {
    mount(shelfContainer({ words: [word("a", { rung: 0 }), word("b", { rung: 1 }), word("c", { rung: 4 }), word("d", { rung: 5 }), word("e", { rung: 2, saved: false })] }));
    expect(await screen.findByRole("button", { name: "See 1 words at level New" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "See 0 words at level Recalled" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "See 2 words at level On my own" }));
    expect(await screen.findByText("at /words?level=4")).toBeInTheDocument();
  });

  it("counts each word once in the status donut", async () => {
    mount(shelfContainer({ words: [
      word("a", { rung: 1 }), word("b", { rung: 3 }), word("c", { status: "suspended", rung: 4 }), word("e", { status: "backlog" }),
    ] }));
    await userEvent.click(await screen.findByRole("button", { name: "Donut chart" }));
    for (const label of ["Learning", "Can use", "Paused"]) expect(screen.getByText(label).querySelector("b")).toHaveTextContent("1");
    expect(screen.getByText("words", { selector: "small" }).parentElement).toHaveTextContent("3");
  });

  it("opens the review settings with the due words chosen, keeps a deck per language, and is disabled when nothing is due", async () => {
    const { unmount } = mount(shelfContainer({ words: [word("a")] }));
    expect(await screen.findByRole("button", { name: "Review now 0 words" })).toBeDisabled();
    unmount();
    mount(shelfContainer({ words: [word("due1", { nextReviewAt: past }), word("later", { nextReviewAt: "2999-01-01T00:00:00Z" })] }));
    expect(await screen.findByRole("link", { name: "Review English: 1 due, 2 new" })).toHaveAttribute("href", "/review/en");
    await userEvent.click(await screen.findByRole("button", { name: "Review now 1 words" }));
    expect(within(screen.getByRole("dialog", { name: "review setup" })).getByText("all|due1|due1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "close review" }));
    expect(screen.queryByRole("dialog", { name: "review setup" })).not.toBeInTheDocument();
  });
  it("keeps the notebooks when the words fail to load", async () => {
    mount(shelfContainer({ wordsFail: true }));
    expect(await screen.findByText("Your words could not be loaded.")).toBeInTheDocument();
    expect(await screen.findByText("Apple")).toBeInTheDocument();
  });

  it("sorts notebooks by name and by reversed server order", async () => {
    mount(shelfContainer());
    await screen.findByText("Apple");
    const names = () => [...document.querySelectorAll(".shelf-group")][0].querySelectorAll("strong");
    expect([...names()].map(node => node.textContent)).toEqual(["Banana", "Apple"]);
    await userEvent.click(screen.getByRole("button", { name: "Sort notebooks" }));
    await userEvent.click(screen.getByRole("button", { name: "Oldest" }));
    expect([...names()].map(node => node.textContent)).toEqual(["Apple", "Banana"]);
    await userEvent.click(screen.getByRole("button", { name: "Z-A" }));
    expect([...names()].map(node => node.textContent)).toEqual(["Banana", "Apple"]);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "Oldest" })).not.toBeInTheDocument();
  });

  it("deletes a notebook after a dialog that says its words stay, and Escape cancels", async () => {
    const c = shelfContainer();
    mount(c);
    await userEvent.click(await screen.findByRole("button", { name: "Options for Apple" }));
    expect(screen.queryByRole("button", { name: /Edit/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    let dialog = screen.getByRole("dialog", { name: "Delete notebook?" });
    expect(dialog).toHaveTextContent("“Apple” will be deleted. Its words stay in All words.");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(c.lists.remove).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Options for Apple" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    dialog = screen.getByRole("dialog", { name: "Delete notebook?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(c.lists.remove).toHaveBeenCalledWith("en-a"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("explains the notebook limit in the create dialog", async () => {
    const c = shelfContainer({ lists: { create: vi.fn(async () => { throw new ApiError("conflict", 409, { code: "too_many_lists" }); }) } });
    mount(c);
    await userEvent.click(await screen.findByRole("button", { name: "Create notebook" }));
    await userEvent.type(screen.getByLabelText("Notebook name"), "One more");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("You have reached the limit of notebooks. Delete one first.")).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    mount(shelfContainer({ lists: { list: vi.fn(async () => []) } }));
    expect(await screen.findByText("No notebooks yet.")).toBeInTheDocument();
  });

  it("links ready-made sets and searches them in a dialog", async () => {
    mount(shelfContainer());
    expect(await screen.findByRole("link", { name: /^HSK 1/ })).toHaveAttribute("href", "/words/sets/hsk1");
    await userEvent.click(screen.getByRole("button", { name: "See more" }));
    const dialog = screen.getByRole("dialog", { name: "Search" });
    await userEvent.type(within(dialog).getByLabelText("Search sets"), "a1");
    expect(within(dialog).queryByRole("link", { name: /HSK 1/ })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /A1/ })).toHaveAttribute("href", "/words/sets/a1");
  });

  it("follows ?tab=grammar when a link changes only the query of the open shelf", async () => {
    const overview = { languageCode: "en", levels: ["A1"], level: "A1", topics: [{ key: "verbs", title: "Verbs" }], redo: [],
      points: [{ key: "en.a1.be", title: "The verb be", topicKey: "verbs", lesson: null, exerciseCount: 4, attempts: 0,
        correctCount: 0, incorrectCount: 0, lessonLearnedAt: null }] };
    const review = { decks: vi.fn(async () => []), grammar: vi.fn(async () => overview) };
    mount({ ...shelfContainer(), review }, "/words/lists", <>
      <Link to="/words/lists?tab=grammar">Open grammar</Link><Link to="/words/lists">Open notebooks</Link>
    </>);
    expect(await screen.findByRole("link", { name: /Practise with Tata/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Open grammar" }));
    expect(await screen.findByRole("heading", { name: "Verbs" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Open notebooks" }));
    expect(await screen.findByRole("link", { name: /Practise with Tata/ })).toBeInTheDocument();
  });

  it("shows grammar in place of the notebooks, opens a lesson and practises it without leaving the page", async () => {
    const exercise = { id: "en.a1.be.1", grammarKey: "en.a1.be", prompt: "She ___ a teacher.",
      options: ["a", "b", "c", "d"].map(id => ({ id, text: `Option ${id}` })) };
    const point = (key: string, title: string, attempts: number, correct: number, lesson: unknown = null) => ({ key, title, topicKey: "verbs",
      lesson, exerciseCount: 4, attempts, correctCount: correct, incorrectCount: attempts - correct, lessonLearnedAt: null });
    const overview = { languageCode: "en", levels: ["A1", "A2"], level: "A1", topics: [{ key: "verbs", title: "Verbs" }], redo: [],
      points: [
        point("en.a1.be", "The verb be", 4, 3, { summary: "Be links a subject to a description.", rules: ["I am, you are, she is"],
          examples: [{ text: "She is a teacher.", meaning: "Cô ấy là giáo viên." }], mistakes: [] }),
        point("en.a1.have", "Have got", 0, 0),
      ] };
    const review = { decks: vi.fn(async () => []), grammar: vi.fn(async () => overview), grammarExercises: vi.fn(async () => [exercise]),
      grammarLessonLearned: vi.fn(async () => undefined) };
    mount({ ...shelfContainer(), review });
    expect(await screen.findByRole("link", { name: /Practise with Tata/ })).toHaveAttribute("href", "/agent?mode=voice&entry=home");
    expect(screen.getByRole("link", { name: /Words from videos/ })).toHaveAttribute("href", "/home");
    await userEvent.click(screen.getByRole("button", { name: "Grammar" }));

    expect(await screen.findByRole("heading", { name: "Verbs" })).toBeInTheDocument();
    expect(screen.getAllByText("1/2")).toHaveLength(2);
    expect(screen.getByText("3 correct, 1 wrong")).toBeInTheDocument();
    expect(review.grammar).toHaveBeenCalledWith("en", undefined);
    expect(screen.queryByRole("button", { name: "Create notebook" })).not.toBeInTheDocument();
    expect(screen.queryByText(/^at \//)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /The verb be/ }));
    // The lesson takes the place of the points, in the same column.
    expect(screen.getByRole("heading", { name: "The verb be" })).toBeInTheDocument();
    expect(screen.getByText("She is a teacher.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mark the lesson as learned" }));
    await waitFor(() => expect(review.grammarLessonLearned).toHaveBeenCalledWith("en", "en.a1.be", expect.any(String)));
    await userEvent.click(screen.getByRole("button", { name: "Practise this point" }));

    expect(await screen.findByText("She ___ a teacher.")).toBeInTheDocument();
    expect(review.grammarExercises).toHaveBeenLastCalledWith("en", { grammarKey: "en.a1.be" });
    expect(screen.queryByText(/^at \//)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back to grammar points" }));
    expect(screen.getByRole("heading", { name: "Verbs" })).toBeInTheDocument();
  });
});
function setPage(offset: number, count: number, total = 120) {
  return {
    key: "hsk1", languageCode: "zh", name: "HSK 1", wordCount: total, offset,
    words: Array.from({ length: count }, (_, n) => ({
      entryId: `e${offset + n}`, senseId: `s${offset + n}`, text: `字${offset + n}`, traditional: n === 0 ? "字體" : null, reading: "zì", meaning: "a character",
    })),
  };
}

function setContainer(overrides: { addFromSet?: unknown; set?: unknown; create?: unknown } = {}) {
  return {
    notebook: {
      set: overrides.set ?? vi.fn(async (_key: string, offset: number) => setPage(offset, offset >= 100 ? 20 : 50)),
      addFromSet: overrides.addFromSet ?? vi.fn(async () => ({ ...emptyReport(), matched: 2, alreadyInList: 1 })),
    },
    lists: {
      list: vi.fn(async () => parseListSummaries([ZH])),
      create: overrides.create ?? vi.fn(async () => parseListSummaries([raw("zh-new", "Fresh", "zh", 0)])[0]),
    },
  };
}

describe("Ready-made set page", () => {
  const open = (c: unknown) => mount(c, "/words/sets/hsk1");

  it("shows the words with traditional form, reading and meaning, and goes back to the shelf", async () => {
    open(setContainer());
    expect(await screen.findByRole("heading", { name: "HSK 1", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("120 words")).toBeInTheDocument();
    expect(screen.getByText("【字體】")).toBeInTheDocument();
    expect(screen.getAllByText("a character")).toHaveLength(50);
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute("href", "/words/lists");
  });

  it("pages by fifty and clears the selection on a new page", async () => {
    const c = setContainer();
    open(c);
    await screen.findByText("字0");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByRole("button", { name: /^字0/ }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("字50");
    expect(c.notebook.set).toHaveBeenLastCalledWith("hsk1", 50);
    expect(screen.getByRole("button", { name: "Add to notebook" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("字100");
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByText("101–120 of 120")).toBeInTheDocument();
  });

  it("adds the selected words to a notebook and reports how many were added", async () => {
    const c = setContainer();
    open(c);
    await screen.findByText("字0");
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByRole("button", { name: /^字0/ }));
    await userEvent.click(screen.getByRole("button", { name: /^字1(?![0-9])/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to notebook" }));
    const dialog = screen.getByRole("dialog", { name: "Add to notebook" });
    expect(c.lists.list).toHaveBeenCalledWith("zh");
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeDisabled();
    await userEvent.click(await within(dialog).findByRole("button", { name: /HSK notes/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(c.notebook.addFromSet).toHaveBeenCalledWith("zh-1", ["e0", "e1"]));
    expect(await screen.findByText("2 added to “HSK notes” · 1 already in the notebook")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select" })).toBeInTheDocument();
  });

  it("sends at most fifty words when all are selected", async () => {
    const c = setContainer();
    open(c);
    await screen.findByText("字0");
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByRole("button", { name: "Select all" }));
    await userEvent.click(screen.getByRole("button", { name: "Add to notebook" }));
    await userEvent.click(await screen.findByRole("button", { name: /HSK notes/ }));
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(c.notebook.addFromSet).toHaveBeenCalled());
    expect((c.notebook.addFromSet as ReturnType<typeof vi.fn>).mock.calls[0][1]).toHaveLength(50);
  });

  it("creates a notebook in the set's language from the dialog and adds to it", async () => {
    const c = setContainer();
    open(c);
    await screen.findByText("字0");
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByRole("button", { name: /^字0/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to notebook" }));
    await userEvent.click(screen.getByRole("button", { name: "Create notebook" }));
    await userEvent.type(screen.getByLabelText("Notebook name"), " Fresh ");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(c.lists.create).toHaveBeenCalledWith("zh", "Fresh"));
    await userEvent.click(await screen.findByRole("button", { name: "Done" }));
    await waitFor(() => expect(c.notebook.addFromSet).toHaveBeenCalledWith("zh-new", ["e0"]));
    expect(await screen.findByText("2 added to “Fresh” · 1 already in the notebook")).toBeInTheDocument();
  });

  it("says when the notebook is full", async () => {
    const c = setContainer({ addFromSet: vi.fn(async () => ({ ...emptyReport(), listFull: true })) });
    open(c);
    await screen.findByText("字0");
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByRole("button", { name: /^字0/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to notebook" }));
    await userEvent.click(await screen.findByRole("button", { name: /HSK notes/ }));
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByText("The notebook is full. Remove a word to add more.")).toBeInTheDocument();
  });

  it("says when the set does not exist", async () => {
    open(setContainer({ set: vi.fn(async () => { throw new ApiError("not_found", 404, {}); }) }));
    expect(await screen.findByText("This set was not found.")).toBeInTheDocument();
  });
});
