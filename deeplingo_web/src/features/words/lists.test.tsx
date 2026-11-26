import { fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import {
  addReports,
  emptyReport,
  parseImportReport,
  parseListDetail,
  parseListSummaries,
  splitIntoBatches,
  type ImportReport,
  type ListDetail,
} from "./listsModels";
import type { WordDetails, WordImage } from "./notebookApi";
import { WordListScreen } from "./WordListScreen";
import { WordListsScreen } from "./WordListsScreen";

vi.mock("../notebookStudy/ReviewSetupSheet", () => ({
  ReviewSetupSheet: (props: { scope: string; preselected?: string[] }) => <p>review {props.scope}: {props.preselected?.join(",")}</p>,
}));
vi.mock("../notebookStudy/PronounceDialog", () => ({
  PronounceDialog: (props: { words: { text: string }[]; initialIndex?: number }) => <p>pronounce {props.words[props.initialIndex ?? 0].text}</p>,
}));

const LIST = "55555555-5555-5555-5555-555555555555";
const ENTRY = "66666666-6666-6666-6666-666666666666";
const OTHER = "77777777-7777-7777-7777-777777777777";

const rawSummary = { id: LIST, language_code: "en", name: "Travel", description: null, word_count: 1, waiting_count: 2 };
const rawDetail = {
  ...rawSummary,
  words: [{ concept_id: "c1", text: "airport", gloss: "A place for planes.", status: "backlog", rung: 0, level_label: "A2", above_level: false }],
  waiting: [
    { id: "l1", text: "bank", gloss: null, resolution: "ambiguous", candidates: [
      { entry_id: ENTRY, sense_id: "s1", headword: "bank", text: "Where money is kept.", part_of_speech: "noun" },
      { entry_id: ENTRY, sense_id: "s2", headword: "bank", text: "A river side.", part_of_speech: "noun" },
    ] },
    { id: "l2", text: "zzz", gloss: null, resolution: "unresolved", candidates: [] },
  ],
};
const rawReport = { matched: 1, ambiguous: 0, unresolved: 0, already_in_list: 0, duplicates: 0, too_long: 0, over_limit: 0, above_level: 0, list_full: false };

function report(overrides: Partial<ImportReport> = {}): ImportReport {
  return { ...parseImportReport(rawReport), ...overrides };
}

function mount(ui: React.ReactNode, container: unknown, path: string, route: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={queryClient}>
        <ContainerProvider container={container as AppContainer}>
          <Routes>
            <Route path={route} element={ui} />
            <Route path="/words/lists/:listId" element={<p>list page</p>} />
          </Routes>
        </ContainerProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("word list models", () => {
  it("parses summaries and details and rejects a bad resolution", () => {
    expect(parseListSummaries([rawSummary])[0]).toMatchObject({ name: "Travel", wordCount: 1, waitingCount: 2 });
    const detail = parseListDetail(rawDetail);
    expect(detail.waiting[0].candidates).toHaveLength(2);
    expect(detail.words[0]).toMatchObject({ text: "airport", status: "backlog", levelLabel: "A2" });
    expect(() => parseListDetail({ ...rawDetail, waiting: [{ ...rawDetail.waiting[1], resolution: "maybe" }] })).toThrow(ApiError);
    expect(() => parseImportReport({ ...rawReport, list_full: "no" })).toThrow(ApiError);
  });

  it("splits a paste into batches of at most fifty non-empty lines", () => {
    const text = Array.from({ length: 120 }, (_, n) => (n % 10 === 0 ? "" : `word${n}`)).join("\r\n");
    const batches = splitIntoBatches(text);
    expect(batches.map((batch) => batch.split("\n").length)).toEqual([50, 50, 8]);
    expect(splitIntoBatches("  \n\n")).toEqual([]);
  });

  it("adds reports together", () => {
    const sum = addReports(report({ matched: 2 }), report({ matched: 3, listFull: true }));
    expect(sum).toMatchObject({ matched: 5, listFull: true });
    expect(emptyReport().matched).toBe(0);
  });
});

describe("My lists screen", () => {
  function container(overrides: Record<string, unknown> = {}) {
    return {
      onboarding: { loadProfile: vi.fn(async () => ({ learning_language: "en", support_language: "vi" })) },
      lists: {
        list: vi.fn(async () => parseListSummaries([rawSummary])),
        create: vi.fn(async () => parseListSummaries([rawSummary])[0]),
        ...overrides,
      },
      words: { list: vi.fn(async () => ({ words: [], summary: null })) },
      notebook: { sets: vi.fn(async () => []) },
    };
  }

  it("shows the lists and creates one in the learning language, then opens it", async () => {
    const c = container();
    mount(<WordListsScreen />, c, "/words/lists", "/words/lists");
    expect(await screen.findByText("Travel")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "English" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Notebooks" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create notebook" }));
    await userEvent.type(screen.getByLabelText("Notebook name"), "  IELTS ");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(c.lists.create).toHaveBeenCalledWith("en", "IELTS"));
    expect(await screen.findByText("list page")).toBeInTheDocument();
  });

  it("explains a name that is already taken", async () => {
    const taken = new ApiError("conflict", 409, { code: "list_name_taken" });
    const c = container({ create: vi.fn(async () => { throw taken; }) });
    mount(<WordListsScreen />, c, "/words/lists", "/words/lists");
    await userEvent.click(await screen.findByRole("button", { name: "Create notebook" }));
    await userEvent.type(await screen.findByLabelText("Notebook name"), "Travel");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("You already have a notebook with that name.")).toBeInTheDocument();
  });
});

describe("One list screen", () => {
  function container(overrides: Record<string, unknown> = {}) {
    const detail: ListDetail = parseListDetail(rawDetail);
    return {
      lists: {
        detail: vi.fn(async () => detail),
        importBatch: vi.fn<(listId: string, text: string) => Promise<ImportReport>>(async () => report()),
        chooseMeaning: vi.fn(async () => detail.words[0]),
        dismissLine: vi.fn(async () => undefined),
        removeWord: vi.fn(async () => undefined),
        remove: vi.fn(async () => undefined),
        addWord: vi.fn(async () => undefined),
        list: vi.fn(async () => parseListSummaries([
          rawSummary, { ...rawSummary, id: OTHER, name: "Work" }, { ...rawSummary, id: "zh-list", language_code: "zh", name: "HSK" },
        ])),
        ...overrides,
      },
      notebook: {
        details: vi.fn(async (conceptId: string): Promise<WordDetails> => ({ conceptId, text: "airport", traditional: null, reading: null, level: null, senses: [], characters: [], compounds: [] })),
        images: vi.fn(async (): Promise<WordImage[]> => []),
        setPersonal: vi.fn(async () => undefined),
        audioUrl: vi.fn(async (_language: string, text: string) => `blob:${text}`),
      },
      words: { examples: vi.fn(async () => []), writeExample: vi.fn(), setStatus: vi.fn(async () => undefined), remove: vi.fn(async () => undefined) },
    };
  }
  const open = (c: unknown) => mount(<WordListScreen />, c, `/words/lists/${LIST}`, "/words/lists/:listId");
  const manyWords = (count: number) => parseListDetail({
    ...rawDetail, waiting: [],
    words: Array.from({ length: count }, (_, n) => ({ ...rawDetail.words[0], concept_id: `c${n}`, text: `word${n}` })),
  });
  const pasted = Array.from({ length: 120 }, (_, n) => `word${n}`).join("\n");
  async function openPaste() {
    await userEvent.click(await screen.findByRole("button", { name: "Options" }));
    await userEvent.click(screen.getByRole("button", { name: "Paste many words" }));
    await userEvent.click(await screen.findByLabelText("Paste words, one per line"));
  }

  it("shows the words, opens the lines waiting for the learner and links to the study tools", async () => {
    const c = container();
    open(c);
    expect(await screen.findByText("airport")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "2 words need a meaning" }));
    expect(await screen.findByText("Where money is kept.")).toBeInTheDocument();
    expect(screen.getByText(/Not found in the dictionary/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("link", { name: "Flashcards" })).toHaveAttribute("href", `/notebook/${LIST}/flashcards`);
    // Writing is for Chinese and Japanese characters only: an English notebook has no Writing tile.
    expect(screen.queryByRole("link", { name: "Writing" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Practise with Tata/ })).toHaveAttribute("href", `/agent?mode=voice&practice=roleplay&entry=home&topic=${LIST}`);
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute("href", "/words/lists");
    // Opening the notebook writes nothing and asks for no pictures in list view.
    expect(c.notebook.images).not.toHaveBeenCalled();
    expect(c.notebook.setPersonal).not.toHaveBeenCalled();
    expect(c.lists.addWord).not.toHaveBeenCalled();
  });

  it("sends a long paste in batches of at most fifty lines and reports the total", async () => {
    const c = container();
    open(c);
    await openPaste();
    await userEvent.paste(pasted);
    await userEvent.click(screen.getByRole("button", { name: "Add words" }));
    await waitFor(() => expect(c.lists.importBatch).toHaveBeenCalledTimes(3));
    expect(c.lists.importBatch.mock.calls.map((call) => (call[1] as string).split("\n").length)).toEqual([50, 50, 20]);
    expect(c.lists.importBatch.mock.calls.every((call) => call[0] === LIST)).toBe(true);
    expect(await screen.findByText("3 added")).toBeInTheDocument();
  });

  it("stops at the first failed batch and says it is safe to try again", async () => {
    const importBatch = vi.fn()
      .mockResolvedValueOnce(report())
      .mockRejectedValueOnce(new ApiError("network", null, {}))
      .mockResolvedValue(report());
    open(container({ importBatch }));
    await openPaste();
    await userEvent.paste(pasted);
    await userEvent.click(screen.getByRole("button", { name: "Add words" }));
    expect(await screen.findByText(/Batch 2 of 3 could not be sent/)).toBeInTheDocument();
    expect(importBatch).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("Paste words, one per line")).toHaveValue(pasted);
  });

  it("stops when the list is full", async () => {
    const importBatch = vi.fn(async () => report({ listFull: true }));
    open(container({ importBatch }));
    await openPaste();
    await userEvent.paste(pasted);
    await userEvent.click(screen.getByRole("button", { name: "Add words" }));
    expect(await screen.findByText("The notebook is full. Remove a word to add more.")).toBeInTheDocument();
    expect(importBatch).toHaveBeenCalledTimes(1);
  });

  it("sends only a stored candidate when the learner picks a meaning, and can dismiss a line", async () => {
    const c = container();
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "2 words need a meaning" }));
    await userEvent.click(await screen.findByRole("button", { name: "Use this meaning for bank: A river side." }));
    await waitFor(() => expect(c.lists.chooseMeaning).toHaveBeenCalledWith(LIST, "l1", ENTRY, "s2"));
    await userEvent.click(screen.getByRole("button", { name: "Dismiss zzz" }));
    await waitFor(() => expect(c.lists.dismissLine).toHaveBeenCalledWith(LIST, "l2"));
  });

  it("removes a word from the list only, after saying it stays in All words", async () => {
    const c = container();
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Open airport" }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove from notebook" }));
    expect(c.lists.removeWord).not.toHaveBeenCalled();
    expect(screen.getByText("They stay in All words.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove from notebook" }));
    await waitFor(() => expect(c.lists.removeWord).toHaveBeenCalledWith(LIST, "c1"));
    expect(c.words.remove).not.toHaveBeenCalled();
  });

  it("finds a word by its text, reading or meaning without tone marks", async () => {
    const detail = parseListDetail({ ...rawDetail, waiting: [], words: [
      rawDetail.words[0],
      { ...rawDetail.words[0], concept_id: "c2", text: "妈妈", reading: "māma", gloss: "mẹ" },
      { ...rawDetail.words[0], concept_id: "c3", text: "reserve", gloss: "đặt chỗ" },
    ] });
    open(container({ detail: vi.fn(async () => detail) }));
    const search = await screen.findByRole("searchbox", { name: "Search words" });
    await userEvent.type(search, "dat cho");
    expect(screen.getByText("reserve")).toBeInTheDocument();
    expect(screen.queryByText("airport")).not.toBeInTheDocument();
    await userEvent.clear(search);
    await userEvent.type(search, "mama");
    expect(screen.getByText("妈妈")).toBeInTheDocument();
    expect(screen.queryByText("reserve")).not.toBeInTheDocument();
    await userEvent.clear(search);
    await userEvent.type(search, "zzzz");
    expect(screen.getByText("No words here.")).toBeInTheDocument();
  });

  it("keeps the server's order as newest and sorts the rest", async () => {
    const detail = parseListDetail({ ...rawDetail, waiting: [], words: [
      { ...rawDetail.words[0], concept_id: "c1", text: "beta" }, { ...rawDetail.words[0], concept_id: "c2", text: "gamma" }, { ...rawDetail.words[0], concept_id: "c3", text: "alpha" },
    ] });
    open(container({ detail: vi.fn(async () => detail) }));
    const order = () => screen.getAllByRole("button", { name: /^Open / }).map(tile => tile.getAttribute("aria-label"));
    await screen.findByText("beta");
    expect(order()).toEqual(["Open beta", "Open gamma", "Open alpha"]);
    await userEvent.click(screen.getByRole("button", { name: "Options" }));
    await userEvent.click(screen.getByRole("button", { name: "Oldest" }));
    expect(order()).toEqual(["Open alpha", "Open gamma", "Open beta"]);
    await userEvent.click(screen.getByRole("button", { name: "A-Z" }));
    expect(order()).toEqual(["Open alpha", "Open beta", "Open gamma"]);
    await userEvent.click(screen.getByRole("button", { name: "Z-A" }));
    expect(order()).toEqual(["Open gamma", "Open beta", "Open alpha"]);
  });

  it("removes selected words one at a time, and trying again finishes only the rest", async () => {
    const removeWord = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new ApiError("network", null, {})).mockResolvedValue(undefined);
    const c = container({ detail: vi.fn(async () => manyWords(2)), removeWord });
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Select all" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("They stay in All words.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove from notebook" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Some words could not be changed");
    expect(removeWord.mock.calls).toEqual([[LIST, "c0"], [LIST, "c1"]]);
    await userEvent.click(screen.getByRole("button", { name: "Remove from notebook" }));
    await waitFor(() => expect(removeWord).toHaveBeenCalledTimes(3));
    expect(removeWord).toHaveBeenLastCalledWith(LIST, "c1");
    expect(await screen.findByText("Removed 1 words from this notebook")).toBeInTheDocument();
    expect(c.words.remove).not.toHaveBeenCalled();
  });

  it("moves words to another notebook of the same language, adding before removing", async () => {
    const addWord = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new ApiError("conflict", 409, { code: "list_full" })).mockResolvedValue(undefined);
    const c = container({ detail: vi.fn(async () => manyWords(2)), addWord });
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Select all" }));
    await userEvent.click(screen.getByRole("button", { name: "Move" }));
    await userEvent.click(await screen.findByRole("button", { name: /Work/ }));
    expect(screen.queryByRole("button", { name: /HSK/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Travel/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That notebook is full");
    expect(addWord.mock.calls).toEqual([[OTHER, "c0"], [OTHER, "c1"]]);
    expect(c.lists.removeWord.mock.calls).toEqual([[LIST, "c0"]]);
    expect(addWord.mock.invocationCallOrder[0]).toBeLessThan(c.lists.removeWord.mock.invocationCallOrder[0]);
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(c.lists.removeWord).toHaveBeenCalledTimes(2));
    expect(addWord).toHaveBeenLastCalledWith(OTHER, "c1");
    expect(c.lists.removeWord).toHaveBeenLastCalledWith(LIST, "c1");
  });

  it("creates a notebook from the move dialog and chooses it", async () => {
    const created = parseListSummaries([{ ...rawSummary, id: "new-list", name: "Fresh" }])[0];
    const create = vi.fn(async () => created);
    const c = container({ create });
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Select airport" }));
    await userEvent.click(screen.getByRole("button", { name: "Move" }));
    await userEvent.click(await screen.findByRole("button", { name: "New notebook" }));
    await userEvent.type(screen.getByLabelText("Notebook name"), " Fresh ");
    await userEvent.click(screen.getByRole("button", { name: "Create notebook" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith("en", "Fresh"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Done" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(c.lists.addWord).toHaveBeenCalledWith("new-list", "c1"));
  });

  it("edits the note only, for one selected word", async () => {
    const c = container({ detail: vi.fn(async () => manyWords(2)) });
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByRole("button", { name: "Edit word" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Select word0" }));
    await userEvent.click(screen.getByRole("button", { name: "Edit word" }));
    await userEvent.type(await screen.findByRole("textbox", { name: "Note" }), " remember this ");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(c.notebook.setPersonal).toHaveBeenCalledWith("c0", { note: "remember this" }));
  });

  it("clears a note left empty and keeps the dialog open when saving fails", async () => {
    const detail = parseListDetail({ ...rawDetail, waiting: [], words: [{ ...rawDetail.words[0], note: "old" }] });
    const c = container({ detail: vi.fn(async () => detail) });
    c.notebook.setPersonal.mockRejectedValueOnce(new ApiError("server", 500, {})).mockResolvedValue(undefined);
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Note for airport" }));
    await userEvent.clear(await screen.findByRole("textbox", { name: "Note" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The note could not be saved");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(c.notebook.setPersonal).toHaveBeenLastCalledWith("c1", { note: null }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("adds a looked-up word to this notebook", async () => {
    const c = container();
    Object.assign(c.words, {
      search: vi.fn(async () => [{ entryId: "e1", headword: "gate", level: "A2", sourceName: "Wiktionary", sourceLicense: "CC BY-SA 4.0", sourceUrl: "https://en.wiktionary.org/wiki/gate",
        senses: [{ senseId: "s1", text: "A door.", partOfSpeech: "noun", reading: null, example: null, meaning: "cổng" }] }]),
      save: vi.fn(async () => ({ conceptId: "new", text: "gate" })),
    });
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Add word" }));
    await userEvent.type(await screen.findByLabelText("Add a word"), "gate");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    await waitFor(() => expect(c.lists.addWord).toHaveBeenCalledWith(LIST, "new"));
    expect(await screen.findByText(/was added to this notebook/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Wiktionary" })).toBeInTheDocument();
  });

  it("explains a full notebook when adding a looked-up word", async () => {
    const c = container({ addWord: vi.fn(async () => { throw new ApiError("conflict", 409, { code: "list_full" }); }) });
    Object.assign(c.words, {
      search: vi.fn(async () => [{ entryId: "e1", headword: "gate", level: null, sourceName: null, sourceLicense: null, sourceUrl: null,
        senses: [{ senseId: "s1", text: "A door.", partOfSpeech: null, reading: null, example: null, meaning: null }] }]),
      save: vi.fn(async () => ({ conceptId: "new", text: "gate" })),
    });
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Add word" }));
    await userEvent.type(await screen.findByLabelText("Add a word"), "gate");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The notebook is full. Remove a word first.");
  });

  it("shows the Chinese tabs, offers Writing, and leaves out sections without data", async () => {
    const detail = parseListDetail({ ...rawDetail, language_code: "zh", waiting: [], words: [
      { ...rawDetail.words[0], concept_id: "z1", text: "妈妈", traditional: "媽媽", reading: "māma", gloss: "mẹ", level_label: "HSK 1" },
    ] });
    const c = container({ detail: vi.fn(async () => detail) });
    c.notebook.details.mockResolvedValue({ conceptId: "z1", text: "妈妈", traditional: "媽媽", reading: "māma", level: "HSK 1",
      senses: [{ text: "mother", reading: null, partOfSpeech: "noun" }],
      characters: [{ character: "妈", reading: "mā", meaning: "mẹ" }], compounds: [{ text: "妈妈们", reading: null, meaning: "các mẹ" }] });
    open(c);
    expect(await screen.findByText("【媽媽】")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Writing" })).toHaveAttribute("href", `/notebook/${LIST}/writing`);
    await userEvent.click(screen.getByRole("button", { name: "Open 妈妈" }));
    const sheet = await screen.findByRole("dialog", { name: "妈妈" });
    expect(within(sheet).getAllByRole("tab").map(tab => tab.textContent)).toEqual(["Vocabulary", "Characters", "Examples", "Compounds"]);
    expect(await within(sheet).findByRole("button", { name: "noun" })).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: "Picture" })).not.toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("tab", { name: "Characters" }));
    expect(within(sheet).getByText("妈")).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("tab", { name: "Compounds" }));
    expect(within(sheet).getByText("妈妈们")).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("tab", { name: "Vocabulary" }));
    await userEvent.click(within(sheet).getByRole("button", { name: "Favourite" }));
    await waitFor(() => expect(c.notebook.setPersonal).toHaveBeenCalledWith("z1", { favorite: true }));
    await userEvent.click(within(sheet).getByRole("button", { name: "Pronunciation" }));
    expect(await screen.findByText("pronounce 妈妈")).toBeInTheDocument();
  });

  it("closes the word sheet with Escape, and hides Chinese tabs on an English word", async () => {
    const c = container();
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Open airport" }));
    const sheet = await screen.findByRole("dialog", { name: "airport" });
    expect(within(sheet).getAllByRole("tab").map(tab => tab.textContent)).toEqual(["Vocabulary", "Examples"]);
    expect(c.words.writeExample).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("asks for pictures in batches of 24, with alt text and a colour block when there is none", async () => {
    const c = container({ detail: vi.fn(async () => manyWords(30)) });
    c.notebook.images.mockResolvedValueOnce([{ conceptId: "c0", imageUrl: "https://img/full.jpg", thumbnailUrl: "https://img/t.jpg", title: "A plane", creator: "Ann", license: "cc-by", sourceUrl: "https://img/page" }]);
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Show pictures" }));
    await waitFor(() => expect(c.notebook.images).toHaveBeenCalledTimes(2));
    const calls = c.notebook.images.mock.calls as unknown as [string[]][];
    expect(calls.map(call => call[0].length)).toEqual([24, 6]);
    expect(await screen.findByRole("img", { name: "A plane" })).toHaveAttribute("src", "https://img/t.jpg");
    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(screen.getByText("word29").closest("li")!.querySelector(".nbp-word__img")).toHaveTextContent("W");
  });

  it("shows a picture's credit and asks for another one", async () => {
    const first = { conceptId: "c1", imageUrl: "https://img/a.jpg", thumbnailUrl: null, title: "A plane", creator: "Ann", license: "cc-by", sourceUrl: "https://img/page" };
    const second = { ...first, imageUrl: "https://img/b.jpg", title: "A runway", creator: "Bo", sourceUrl: "javascript:alert(1)" };
    const c = container();
    c.notebook.images.mockResolvedValueOnce([first]).mockResolvedValueOnce([second]);
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Open airport" }));
    expect(await screen.findByRole("link", { name: "Ann, CC-BY" })).toHaveAttribute("href", "https://img/page");
    await userEvent.click(screen.getByRole("button", { name: "Another picture" }));
    await waitFor(() => expect(c.notebook.images).toHaveBeenLastCalledWith(["c1"], "c1"));
    expect(await screen.findByText(/Bo, CC-BY/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Bo, CC-BY" })).not.toBeInTheDocument(); // Not a web link.
  });

  it("opens review with the first five words preselected", async () => {
    open(container({ detail: vi.fn(async () => manyWords(6)) }));
    await userEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByText(`review ${LIST}: c0,c1,c2,c3,c4`)).toBeInTheDocument();
  });

  it("deletes the notebook after a confirmation", async () => {
    const c = container();
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Delete notebook" }));
    expect(c.lists.remove).not.toHaveBeenCalled();
    expect(screen.getByText(/Travel.*will be deleted/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(c.lists.remove).toHaveBeenCalledWith(LIST));
  });

  it("reads the words in order and stops when asked", async () => {
    const played: { onended: (() => void) | null; src: string }[] = [];
    vi.stubGlobal("Audio", class { onended: (() => void) | null = null; playbackRate = 1; constructor(public src: string) { played.push(this); } play() { return Promise.resolve(); } pause() {} });
    URL.revokeObjectURL = vi.fn();
    const c = container({ detail: vi.fn(async () => manyWords(3)) });
    open(c);
    await userEvent.click(await screen.findByRole("button", { name: "Play all" }));
    await waitFor(() => expect(played).toHaveLength(1));
    expect(played[0].src).toBe("blob:word0");
    played[0].onended?.();
    await waitFor(() => expect(played).toHaveLength(2));
    expect(played[1].src).toBe("blob:word1");
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    played[1].onended?.();
    await waitFor(() => expect(screen.getByRole("button", { name: "Play all" })).toBeInTheDocument());
    expect(played).toHaveLength(2);
    vi.unstubAllGlobals();
  });

  it("says when the list is not found", async () => {
    const detail = vi.fn(async () => { throw new ApiError("not_found", 404, { code: "list_not_found" }); });
    open(container({ detail }));
    expect(await screen.findByText("This notebook was not found.")).toBeInTheDocument();
  });
});
