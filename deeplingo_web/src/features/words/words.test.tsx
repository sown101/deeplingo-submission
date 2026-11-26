import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { LookupSheet } from "../concept/LookupSheet";
import { MyWordsScreen } from "./MyWordsScreen";
import { WordActions } from "./WordActions";
import { WordsApi } from "./wordsApi";
import { aboveLevelNotice, parseExamples, parseMyWords, parseMyWordsView, type MyWord } from "./wordsModels";

const CONCEPT = "33333333-3333-3333-3333-333333333333";
const LIB = "11111111-1111-1111-1111-111111111111";
const LO = "44444444-4444-4444-4444-444444444444";

const rawWord = {
  concept_id: CONCEPT, language_code: "en", text: "give up", kind: "expression", gloss: "To stop trying.",
  list: "saved", saved: true, save_source: "lookup", added_at: "2026-10-16T00:00:00Z",
  next_review_at: null,
};

function word(overrides: Partial<MyWord> = {}): MyWord {
  return { ...parseMyWords({ words: [rawWord] })[0], ...overrides };
}

const details = { traditional: null, reading: null, level: null, senses: [], characters: [], compounds: [] };
// The reference data the word sheet reads; screens under test add what they need on top.
const notebookStub = () => ({ details: vi.fn(async (conceptId: string) => ({ ...details, conceptId, text: "x" })), images: vi.fn(async () => []) });
const openSheet = async (text: string) => userEvent.click(await screen.findByRole("button", { name: `Open ${text}` }));

// The level pages of the shelf chart are the screen for every saved word of a level ("All words" was removed).
function mount(ui: React.ReactNode, container: unknown, path = "/words?level=0", route = "/words") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const withNotebook = { notebook: notebookStub(), ...(container as object) };
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={queryClient}>
        <ContainerProvider container={withNotebook as unknown as AppContainer}>
          <Routes><Route path={route} element={ui} /></Routes>
        </ContainerProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("My words models", () => {
  it("parses the server view and rejects an unknown list", () => {
    expect(parseMyWords({ words: [rawWord] })[0]).toMatchObject({ conceptId: CONCEPT, list: "saved", saveSource: "lookup" });
    expect(() => parseMyWords({ words: [{ ...rawWord, list: "mastered" }] })).toThrow(ApiError);
    expect(() => parseMyWords({ words: [{ ...rawWord, saved: "yes" }] })).toThrow(ApiError);
  });
});

describe("My words screen", () => {
  function words() {
    return {
      list: vi.fn(async () => ({ words: [word(), word({ conceptId: "c2", text: "airport" })], summary: null })),
      remove: vi.fn(async () => undefined),
      search: vi.fn(async () => [{
        entryId: "e1", headword: "take off", level: "A2", sourceName: "Wiktionary", sourceLicense: "CC BY-SA 4.0",
        sourceUrl: "https://en.wiktionary.org/wiki/take_off",
        senses: [{ senseId: "s1", text: "To leave the ground.", partOfSpeech: "verb", reading: null, example: null, meaning: "cất cánh" }],
      }]),
      save: vi.fn(async () => word({ text: "take off" })),
    };
  }
  const onboarding = { loadProfile: vi.fn(async () => ({ learning_language: "en", support_language: "vi" })) };

  it("lists saved words, finds one and removes it after saying the removal is complete", async () => {
    const api = words();
    mount(<MyWordsScreen />, { words: api, onboarding });
    expect(await screen.findByText("give up")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith("en");
    // M1 Q1: mastery is not shown on web.
    expect(screen.queryByText(/Mastery/)).not.toBeInTheDocument();

    await userEvent.type(screen.getByRole("searchbox", { name: "Search words" }), "airp");
    expect(screen.queryByText("give up")).not.toBeInTheDocument();
    expect(screen.getByText("airport")).toBeInTheDocument();

    await openSheet("airport");
    await userEvent.click(await screen.findByRole("button", { name: "Remove word" }));
    expect(api.remove).not.toHaveBeenCalled();
    expect(screen.getByText("They will be removed from All words and from every notebook.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove word" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith("c2"));
  });

  it("offers Add to notebook instead of Move, with no removal", async () => {
    const api = words();
    const lists = {
      list: vi.fn(async () => [{ id: "l1", languageCode: "en", name: "Travel", description: null, wordCount: 3, waitingCount: 0 }]),
      addWord: vi.fn(async () => undefined), removeWord: vi.fn(async () => undefined),
    };
    mount(<MyWordsScreen />, { words: api, onboarding, lists });
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Select give up" }));
    expect(screen.queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add to notebook" }));
    await userEvent.click(await screen.findByRole("button", { name: /Travel/ }));
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(lists.addWord).toHaveBeenCalledWith("l1", CONCEPT));
    expect(lists.removeWord).not.toHaveBeenCalled();
    expect(api.remove).not.toHaveBeenCalled();
  });

  it("shows one level of the shelf chart and studies only that scope", async () => {
    const api = words();
    api.list.mockResolvedValue({ words: [word({ rung: 5 }), word({ conceptId: "c2", text: "rely on", rung: 4 }), word({ conceptId: "c3", text: "look up", rung: 1 })], summary: null });
    mount(<MyWordsScreen />, { words: api, onboarding }, "/words?level=4", "/words");
    expect(await screen.findByRole("heading", { name: "Level: Used on your own" })).toBeInTheDocument();
    expect(screen.getByText("give up")).toBeInTheDocument();
    expect(screen.getByText("rely on")).toBeInTheDocument();
    expect(screen.queryByText("look up")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Flashcards" })).toHaveAttribute("href", "/notebook/level-4/flashcards");
    expect(screen.queryByRole("link", { name: "Writing" })).not.toBeInTheDocument();
  });

  it("goes back to the shelf without a level: the All words page was removed", async () => {
    function Shelf() {
      return useLocation().pathname === "/words/lists" ? <output>shelf</output> : <MyWordsScreen />;
    }
    mount(<Shelf />, { words: words(), onboarding }, "/words?level=9", "*");
    expect(await screen.findByText("shelf")).toBeInTheDocument();
  });

  it("offers no delete-notebook or paste tools on a level page", async () => {
    mount(<MyWordsScreen />, { words: words(), onboarding });
    await screen.findByText("give up");
    expect(screen.queryByRole("button", { name: "Delete notebook" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Options" }));
    expect(screen.queryByRole("button", { name: "Paste many words" })).not.toBeInTheDocument();
  });

  it("adds a word by hand by choosing one dictionary sense", async () => {
    const api = words();
    mount(<MyWordsScreen />, { words: api, onboarding });
    await userEvent.click(await screen.findByRole("button", { name: "Add word" }));
    await userEvent.type(await screen.findByLabelText("Add a word"), "take off");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    const result = await screen.findByText("(To leave the ground.)");
    expect(screen.getByText("cất cánh", { exact: false })).toBeInTheDocument();
    await userEvent.click(within(result.closest("li")!).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledWith({
      source: "dictionary", language_code: "en", entry_id: "e1", sense_id: "s1",
    }));
    expect(await screen.findByText(/was added to your words/)).toBeInTheDocument();
  });
});

describe("Examples for a saved word", () => {
  const dictionary = {
    id: "x1", text: "She will give up smoking.", start_codepoint: 9, end_codepoint: 16, translation: null,
    source_kind: "dictionary", ai_generated: false, source_name: "Wiktionary", license_name: "CC BY-SA 4.0",
    license_url: "https://creativecommons.org/licenses/by-sa/4.0/", source_url: "https://en.wiktionary.org/wiki/give_up",
  };
  const generated = {
    id: "x2", text: "I give up, it is too hard.", start_codepoint: 2, end_codepoint: 9, translation: "Tôi bỏ cuộc.",
    source_kind: "generated", ai_generated: true, source_name: null, license_name: null, license_url: null,
    source_url: null,
  };
  const onboarding = { loadProfile: vi.fn(async () => ({ learning_language: "en", support_language: "vi" })) };

  it("rejects an unknown source kind", () => {
    expect(parseExamples({ examples: [dictionary, generated] })).toHaveLength(2);
    expect(() => parseExamples({ examples: [{ ...dictionary, source_kind: "web" }] })).toThrow(ApiError);
    expect(() => parseExamples({ examples: [{ ...dictionary, ai_generated: "no" }] })).toThrow(ApiError);
  });

  it("shows a dictionary example with its credit and licence", async () => {
    const api = {
      list: vi.fn(async () => ({ words: [word()], summary: null })), remove: vi.fn(), search: vi.fn(), save: vi.fn(),
      examples: vi.fn(async () => parseExamples({ examples: [dictionary] })), writeExample: vi.fn(),
    };
    mount(<MyWordsScreen />, { words: api, onboarding });
    await openSheet("give up");
    await userEvent.click(await screen.findByRole("tab", { name: "Examples" }));
    expect(await screen.findByText("give up", { selector: "mark" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Wiktionary" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CC BY-SA 4.0" })).toBeInTheDocument();
    expect(screen.queryByText("Example written by AI")).not.toBeInTheDocument();
    expect(api.examples).toHaveBeenCalledWith(CONCEPT);
    expect(api.writeExample).not.toHaveBeenCalled();
  });

  it("credits a Tatoeba sentence with its author and licence", async () => {
    const corpus = {
      id: "x3", text: "How far away is the airport?", start_codepoint: 20, end_codepoint: 27,
      translation: "Sân bay cách đây bao xa?", source_kind: "corpus", ai_generated: false, source_name: "Tatoeba",
      license_name: "CC BY 2.0 FR", license_url: "https://creativecommons.org/licenses/by/2.0/fr/",
      source_url: "https://tatoeba.org/en/sentences/show/1", author: "langulo",
    };
    const api = {
      list: vi.fn(async () => ({ words: [word()], summary: null })), remove: vi.fn(), search: vi.fn(), save: vi.fn(),
      examples: vi.fn(async () => parseExamples({ examples: [corpus] })), writeExample: vi.fn(),
    };
    mount(<MyWordsScreen />, { words: api, onboarding });
    await openSheet("give up");
    await userEvent.click(await screen.findByRole("tab", { name: "Examples" }));
    expect(await screen.findByRole("link", { name: "Tatoeba" })).toHaveAttribute(
      "href", "https://tatoeba.org/en/sentences/show/1");
    expect(screen.getByRole("link", { name: "CC BY 2.0 FR" })).toBeInTheDocument();
    expect(screen.getByText(/sentence by langulo/)).toBeInTheDocument();
    expect(screen.queryByText("Example written by AI")).not.toBeInTheDocument();
  });

  it("asks the server to write an example and labels it as written by AI", async () => {
    const api = {
      list: vi.fn(async () => ({ words: [word()], summary: null })), remove: vi.fn(), search: vi.fn(), save: vi.fn(),
      examples: vi.fn(async () => []),
      writeExample: vi.fn(async () => parseExamples({ examples: [generated] })),
    };
    mount(<MyWordsScreen />, { words: api, onboarding });
    await openSheet("give up");
    await userEvent.click(await screen.findByRole("tab", { name: "Examples" }));
    await userEvent.click(await screen.findByRole("button", { name: "Find an example" }));
    expect(await screen.findByText("Example written by AI")).toBeInTheDocument();
    expect(screen.getByText("Tôi bỏ cuộc.")).toBeInTheDocument();
    expect(api.writeExample).toHaveBeenCalledWith(CONCEPT);
  });

  it("says so when the server cannot write an example", async () => {
    const api = {
      list: vi.fn(async () => ({ words: [word()], summary: null })), remove: vi.fn(), search: vi.fn(), save: vi.fn(),
      examples: vi.fn(async () => []),
      writeExample: vi.fn(async () => { throw new ApiError("server", 503, { message: "x" }); }),
    };
    mount(<MyWordsScreen />, { words: api, onboarding });
    await openSheet("give up");
    await userEvent.click(await screen.findByRole("tab", { name: "Examples" }));
    await userEvent.click(await screen.findByRole("button", { name: "Find an example" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be found");
  });
});

describe("Saving from a lookup", () => {
  it("sends only the span and the offered sense, never a Concept or a list", async () => {
    const save = vi.fn(async () => word());
    const segment = {
      segment_id: "22222222-2222-2222-2222-222222222222", sequence: 1, text: "She finally gave up smoking.",
      start_ms: 0, end_ms: 2000, translation: null, romanizations: [], learning_objects: [],
    };
    const lookup = vi.fn(async () => ({
      segment_id: segment.segment_id, selection_start: 17, selection_end: 19, unit_start: 12, unit_end: 19,
      unit_text: "gave up", unit_kind: "phrase", selection_is_part: true, headword: "give up", reading: null,
      part_of_speech: "verb", dictionary_gloss: "To stop.", sense_id: "enwikt:giveup1", meaning: "từ bỏ", note: null,
      pattern: [], pattern_explanation: null, examples: [], context_before: null, context_after: null,
      meaning_provenance: "translated_from_sense", level: null,
      source: { name: "Wiktionary", license_name: "CC BY-SA 4.0", license_url: "x", entry_url: "y" },
    }));
    mount(<LookupSheet libraryItemId={LIB} segment={segment} span={{ start: 17, end: 19 }} onClose={vi.fn()} />,
          { playback: { lookup }, words: { save } });
    await userEvent.click(await screen.findByRole("button", { name: "Add to my words" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({
      source: "lookup", library_item_id: LIB, segment_id: segment.segment_id,
      start_codepoint: 17, end_codepoint: 19, sense_id: "enwikt:giveup1",
    }));
    expect(await screen.findByRole("button", { name: "Saved to my words" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Watch this video" })).toHaveAttribute("href", `/library/videos/${LIB}/watch`);
  });
});

describe("A phrase explained in its context", () => {
  const segment = {
    segment_id: "22222222-2222-2222-2222-222222222222", sequence: 4, text: "and then I got my beans paid",
    start_ms: 0, end_ms: 2000, translation: null, romanizations: [], learning_objects: [],
  };
  const explained = {
    segment_id: segment.segment_id, selection_start: 11, selection_end: 23, unit_start: 11, unit_end: 23,
    unit_text: "got my beans", unit_kind: "phrase", selection_is_part: false, headword: "got my beans", reading: null,
    part_of_speech: null, dictionary_gloss: null, sense_id: null, meaning: "được trả tiền cho số đậu", note: null,
    pattern: ["get", "tân ngữ", "V3"], pattern_explanation: "Được người khác làm việc gì cho mình.",
    examples: [{ text: "I got my car fixed.", translation: "Tôi đã mang xe đi sửa." }],
    context_before: "and it cost $10 to get to the farm", context_after: "$8.",
    meaning_provenance: "ai_unverified", level: null, source: null,
  };
  const notebooks = [{ id: "nb-travel", name: "Du lịch", languageCode: "en", wordCount: 3 }, { id: "nb-work", name: "Công việc", languageCode: "en", wordCount: 1 }];

  function open(addWord = vi.fn(async () => undefined)) {
    const save = vi.fn(async () => word());
    const lists = { list: vi.fn(async () => notebooks), addWord, create: vi.fn() };
    mount(<LookupSheet libraryItemId={LIB} segment={segment} span={{ start: 11, end: 23 }} onClose={vi.fn()} />,
          { playback: { lookup: vi.fn(async () => explained) }, words: { save }, lists,
            onboarding: { loadProfile: async () => ({ learning_language: "en", support_language: "vi" }) } });
    return { save, lists };
  }

  it("shows the neighbouring subtitles, the structure and new examples", async () => {
    open();
    expect(await screen.findByLabelText("In context")).toHaveTextContent("and it cost $10 to get to the farm and then I got my beans paid $8.");
    expect(screen.getByText("get")).toHaveClass("lookup-pattern__part");
    expect(screen.getByText("Được người khác làm việc gì cho mình.")).toBeInTheDocument();
    expect(screen.getByText("I got my car fixed.")).toBeInTheDocument();
    expect(screen.getByText("AI explanation, not checked against a dictionary")).toBeInTheDocument();
  });

  it("saves to All words and to each chosen notebook", async () => {
    const { save, lists } = open();
    const places = await screen.findByRole("group", { name: "Save to" });
    await userEvent.click(await within(places).findByRole("button", { name: "Du lịch" }));
    await userEvent.click(screen.getByRole("button", { name: "Save to 2 places" }));
    await waitFor(() => expect(lists.addWord).toHaveBeenCalledWith("nb-travel", word().conceptId));
    expect(save).toHaveBeenCalledTimes(1);
    expect(lists.addWord).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Also added to 1 notebooks.")).toBeInTheDocument();
  });

  it("says so when the word is saved but a notebook could not take it", async () => {
    open(vi.fn(async () => { throw new Error("private detail"); }));
    await userEvent.click(await within(await screen.findByRole("group", { name: "Save to" })).findByRole("button", { name: "Công việc" }));
    await userEvent.click(screen.getByRole("button", { name: "Save to 2 places" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Saved to my words, but not to every notebook.");
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
  });
});

// The one-word practice session was removed (2026-11-05); the notebook's Learn mode asks the same questions.
describe("Saved word examples", () => {
  it("shows a word's examples without a separate practice session", async () => {
    const onboarding = { loadProfile: vi.fn(async () => ({ learning_language: "en", support_language: "vi" })) };
    const examples = parseExamples({ examples: [{
      id: "x1", text: "She will give up smoking.", start_codepoint: 9, end_codepoint: 16, translation: null,
      source_kind: "dictionary", ai_generated: false, source_name: "Wiktionary", license_name: "CC BY-SA 4.0",
      license_url: null, source_url: null,
    }] });
    const words = {
      list: vi.fn(async () => ({ words: [word()], summary: null })), remove: vi.fn(), search: vi.fn(), save: vi.fn(),
      examples: vi.fn(async () => examples), writeExample: vi.fn(),
    };
    mount(<MyWordsScreen />, { words, onboarding });
    await openSheet("give up");
    await userEvent.click(await screen.findByRole("tab", { name: "Examples" }));
    expect(await screen.findByText(/smoking/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Practise this word" })).not.toBeInTheDocument();
  });
});


// --- L1a: targets, the daily gate and the level warning ------------------------------------------

function aboveLevelError(level = "C1", declared = "A2") {
  return new ApiError("conflict", 409, {
    code: "above_level", message: "This word is above your level.",
    raw: { detail: { code: "above_level", message: "This word is above your level.", level, declared_level: declared } },
  });
}

describe("My words targets: models", () => {
  it("reads the target fields and defaults them for an older server", () => {
    expect(parseMyWords({ words: [rawWord] })[0]).toMatchObject({
      status: "active", explicit: true, priority: 0, levelLabel: null, rung: 0, aboveLevel: false,
    });
    const view = parseMyWordsView({
      words: [{ ...rawWord, status: "backlog", explicit: false, priority: 50, level_label: "B1", rung: 4, above_level: true }],
      summary: { backlog: 4, active: 3, suspended: 1, activated_today: 3, daily_new_limit: 10, declared_level: "A2" },
    });
    expect(view.words[0]).toMatchObject({ status: "backlog", explicit: false, priority: 50, levelLabel: "B1", rung: 4, aboveLevel: true });
    expect(view.summary).toEqual({ backlog: 4, active: 3, suspended: 1, activatedToday: 3, dailyNewLimit: 10, declaredLevel: "A2" });
    expect(parseMyWordsView({ words: [] }).summary).toBeNull();
  });

  it("rejects an unknown status, a rung out of range and a malformed summary", () => {
    expect(() => parseMyWords({ words: [{ ...rawWord, status: "mastered" }] })).toThrow(ApiError);
    expect(() => parseMyWords({ words: [{ ...rawWord, rung: 6 }] })).toThrow(ApiError);
    expect(() => parseMyWords({ words: [{ ...rawWord, rung: 1.5 }] })).toThrow(ApiError);
    expect(() => parseMyWordsView({ words: [], summary: { backlog: -1 } })).toThrow(ApiError);
  });

  it("recognises only the server's above-level confirmation", () => {
    expect(aboveLevelNotice(aboveLevelError("B2", "A1"))).toEqual({ level: "B2", declaredLevel: "A1" });
    expect(aboveLevelNotice(new ApiError("conflict", 409, { code: "word_known" }))).toBeNull();
    expect(aboveLevelNotice(new ApiError("validation", 422, { code: "above_level" }))).toBeNull();
    expect(aboveLevelNotice(new Error("x"))).toBeNull();
  });
});

describe("My words targets: screen", () => {
  const onboarding = {
    loadProfile: vi.fn(async () => ({
      learning_language: "en", support_language: "vi", is_complete: true, declared_level: "A2", daily_new_limit: 10,
    })),
  };
  const summary = { backlog: 1, active: 1, suspended: 1, activatedToday: 1, dailyNewLimit: 10, declaredLevel: "A2" };

  function api() {
    // All on the top level of the shelf chart, the page these tests open.
    const waiting = word({ conceptId: "w1", text: "rely on", status: "backlog", levelLabel: "B1", rung: 4, explicit: true });
    const learning = word({ conceptId: "w2", text: "give up", status: "active", rung: 4 });
    const paused = word({ conceptId: "w3", text: "look up", status: "suspended", aboveLevel: true, levelLabel: "C1", rung: 4 });
    return {
      list: vi.fn(async () => ({ words: [waiting, learning, paused], summary })),
      remove: vi.fn(), search: vi.fn(), save: vi.fn(),
      setStatus: vi.fn(async () => waiting),
    };
  }

  it("shows learning and paused words without waiting or a daily gate", async () => {
    mount(<MyWordsScreen />, { words: api(), onboarding }, "/words?level=4");
    await screen.findByText("rely on");
    expect(screen.queryByText(/new words started|Today:|priority/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Waiting/ })).not.toBeInTheDocument();
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Set your level in Profile" })).not.toBeInTheDocument();
    await openSheet("give up");
    expect(await screen.findByText("Used on your own")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await openSheet("look up");
    expect(await screen.findByText("Above your level")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await openSheet("rely on");
    expect(await screen.findByText("Learning")).toBeInTheDocument();
  });

  it("resumes paused words and pauses learning words", async () => {
    const words = api();
    mount(<MyWordsScreen />, { words, onboarding }, "/words?level=4");
    await openSheet("look up");
    await userEvent.click(await screen.findByRole("button", { name: "Resume review" }));
    expect(words.setStatus).toHaveBeenCalledWith("w3", "active");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await openSheet("give up");
    await userEvent.click(await screen.findByRole("button", { name: "Pause review" }));
    expect(words.setStatus).toHaveBeenCalledWith("w2", "suspended");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await openSheet("rely on");
    expect(screen.queryByRole("button", { name: /Learn/ })).not.toBeInTheDocument();
  });

  it("keeps level settings out of My words even when the learner has not declared one", async () => {
    const profile = { ...onboarding, loadProfile: vi.fn(async () => ({ learning_language: "en", support_language: "vi", is_complete: true, declared_level: null })) };
    mount(<MyWordsScreen />, { words: api(), onboarding: profile }, "/words?level=4");
    await screen.findByText("give up");
    expect(screen.queryByRole("link", { name: "Set your level in Profile" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("My level")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("New words per day")).not.toBeInTheDocument();
  });

  it("asks once before adding a word above the learner's level, then adds it", async () => {
    const words = api();
    words.search.mockResolvedValue([{
      entryId: "e9", headword: "ubiquitous", level: "C1", sourceName: null, sourceLicense: null, sourceUrl: null,
      senses: [{ senseId: "s9", text: "Found everywhere.", partOfSpeech: "adj", reading: null, example: null, meaning: null }],
    }]);
    words.save.mockRejectedValueOnce(aboveLevelError()).mockResolvedValueOnce(word({ text: "ubiquitous" }));
    mount(<MyWordsScreen />, { words, onboarding }, "/words?level=4");
    await userEvent.click(await screen.findByRole("button", { name: "Add word" }));
    await userEvent.type(await screen.findByLabelText("Add a word"), "ubiquitous");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    expect(await screen.findByText(/higher than the A2 you set/)).toBeInTheDocument();
    expect(words.save).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Add anyway" }));
    await waitFor(() => expect(words.save).toHaveBeenLastCalledWith({
      source: "dictionary", language_code: "en", entry_id: "e9", sense_id: "s9", acknowledge_above_level: true,
    }));
    expect(await screen.findByText(/was added to your words/)).toBeInTheDocument();
    expect(screen.queryByText(/higher than the A2 you set/)).not.toBeInTheDocument();
  });
});

describe("Add to my words from a transcript", () => {
  const request = { source: "occurrence", library_item_id: LIB, learning_object_id: LO } as const;

  it("saves a word that is within the learner's level straight away", async () => {
    const words = { save: vi.fn(async () => word()) };
    mount(<WordActions save={request} />, { words });
    await userEvent.click(screen.getByRole("button", { name: "Add to my words" }));
    expect(words.save).toHaveBeenCalledWith(request);
    expect(await screen.findByRole("button", { name: "Saved to my words" })).toBeDisabled();
  });

  it("asks for one confirmation for a word above the learner's level and can be cancelled", async () => {
    const words = {
      save: vi.fn(async (body: { acknowledge_above_level?: boolean }) => {
        if (body.acknowledge_above_level) return word();
        throw aboveLevelError("B2", "A1");
      }),
    };
    mount(<WordActions save={request} />, { words });
    await userEvent.click(screen.getByRole("button", { name: "Add to my words" }));
    expect(await screen.findByText(/higher than the A1 you set/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/higher than the A1 you set/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add to my words" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add anyway" }));
    await waitFor(() => expect(words.save).toHaveBeenLastCalledWith({ ...request, acknowledge_above_level: true }));
  });
});


describe("Shared video word actions", () => {
  it("keeps the shared save action usable without a router", async () => {
    const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const words = { save: vi.fn(async () => word()) };
    const view = render(<QueryClientProvider client={query}><ContainerProvider container={{ words } as unknown as AppContainer}>
      <WordActions save={{ source: "occurrence", library_item_id: LIB, learning_object_id: LO }} />
    </ContainerProvider></QueryClientProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Add to my words" }));
    expect(await screen.findByRole("button", { name: "Saved to my words" })).toBeDisabled();
    view.unmount(); query.clear();
  });

  it("asks for the saved word's examples in the background, and a failure there never fails the save", async () => {
    const saved = { concept_id: CONCEPT, language_code: "en", text: "give up", kind: "phrase", gloss: "stop",
      list: "saved", saved: true, save_source: "lookup" };
    const post = vi.fn(async (path: string) => {
      if (path.endsWith("/examples")) throw new Error("rate limited");
      return saved;
    });
    const word = await new WordsApi({ post } as never).save({ source: "dictionary", entry_id: "e", sense_id: "s" } as never);
    expect(word.conceptId).toBe(CONCEPT);
    expect(post.mock.calls.map(call => call[0])).toEqual(["/learner/me/words", `/learner/me/words/${CONCEPT}/examples`]);
    const unsaved = vi.fn(async () => ({ ...saved, saved: false }));
    await new WordsApi({ post: unsaved } as never).save({ source: "dictionary", entry_id: "e", sense_id: "s" } as never);
    expect(unsaved).toHaveBeenCalledTimes(1);
  });

  it("serializes only an optional owned-video selector in the existing word-list request", async () => {
    const get = vi.fn(async (_path: string) => ({ words: [], summary: null }));
    const api = new WordsApi({ get } as never);
    await api.list("zh", LIB); await api.list("en"); await api.list();
    expect(get.mock.calls.map(call => call[0])).toEqual([
      `/learner/me/words?language_code=zh&library_item_id=${LIB}`, "/learner/me/words?language_code=en", "/learner/me/words",
    ]);
  });
});
