import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { startPcmRecorder } from "../../lib/audio/pcmRecorder";
import { FlashcardScreen } from "./FlashcardScreen";
import { PracticeScreen } from "./PracticeScreen";
import { PronounceDialog } from "./PronounceDialog";
import { ReviewSetupSheet } from "./ReviewSetupSheet";
import { WritingScreen } from "./WritingScreen";
import { readReviewParams, reviewHref, reviewItems, serverTypes } from "./studySession";
import type { StudyWord } from "./studyTypes";
import type { Answer, AnswerResult, PronunciationAssessment, ReviewCard } from "../review/reviewModels";

const hanzi = vi.hoisted(() => ({
  options: null as null | Record<string, (...args: unknown[]) => void>,
  create: vi.fn(),
}));
vi.mock("hanzi-writer", () => ({ default: { create: hanzi.create } }));
vi.mock("../../lib/audio/pcmRecorder", async (original) => ({
  ...(await original<typeof import("../../lib/audio/pcmRecorder")>()),
  startPcmRecorder: vi.fn(),
}));

const word = (id: string, text: string, gloss: string | null, extra: Partial<StudyWord> = {}): StudyWord => ({
  conceptId: id, languageCode: "en", text, traditional: null, reading: null, gloss, note: null, favorite: false, ...extra,
});
const listWord = (id: string, text: string, gloss: string) => ({
  conceptId: id, text, gloss, status: "active", rung: 1, levelLabel: null, aboveLevel: false, reading: null, traditional: null,
  note: null, favorite: false,
});
const WORDS = [listWord("a", "airport", "san bay"), listWord("b", "bridge", "cay cau"), listWord("c", "cloud", "dam may")];

function fakes() {
  return {
    notebook: {
      rateMemory: vi.fn(async () => "2026-11-10T00:00:00Z"),
      setPersonal: vi.fn(async () => ({})),
      assessPronunciation: vi.fn(async () => ({ text: "airport", band: "good", pronunciation: 82, accuracy: 80, fluency: 80 })),
      audioUrl: vi.fn(async () => "blob:audio"),
      images: vi.fn(async () => []),
    },
    lists: { detail: vi.fn(async () => ({ id: "nb1", languageCode: "en", name: "Trip", words: WORDS, waiting: [] })) },
    words: { list: vi.fn(), examples: vi.fn(async () => []), writeExample: vi.fn() },
    onboarding: { loadProfile: vi.fn(async () => ({ learning_language: "en", support_language: "vi" })) },
  };
}
type Fakes = ReturnType<typeof fakes>;

function Where() {
  const location = useLocation();
  return <output data-testid="where" data-state={JSON.stringify(location.state)}>{location.pathname + location.search}</output>;
}

function mount(container: Fakes, ui: React.ReactNode, entry: string | { pathname: string; state: unknown }, path: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ContainerProvider container={container as unknown as AppContainer}>
          <Routes><Route path={path} element={ui} /><Route path="*" element={<Where />} /></Routes>
        </ContainerProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

const openFlashcards = async (api: Fakes) => {
  const view = mount(api, <FlashcardScreen />, "/notebook/nb1/flashcards", "/notebook/:scope/flashcards");
  await screen.findByRole("button", { name: "Show the answer" });
  return view;
};
const counter = () => screen.getByTestId("flashcard").querySelector(".st-corner-count")?.textContent;

describe("flashcards", () => {
  const memory = (name: string) => within(screen.getByRole("group", { name: "Memory" })).getByRole("button", { name });

  it("sends only the Memory rating to the schedule, one step later, and has no Can use rating", async () => {
    const api = fakes();
    await openFlashcards(api);
    await userEvent.click(screen.getByRole("button", { name: "Show the answer" }));
    expect(screen.queryByRole("group", { name: "Can use" })).not.toBeInTheDocument();

    await userEvent.click(memory("Unsure"));
    await waitFor(() => expect(counter()).toBe("2 / 3"));
    // The last rating waits so one step back can take it back; the next card's rating sends it.
    expect(api.notebook.rateMemory).not.toHaveBeenCalled();
    await userEvent.click(memory("Remembered"));
    await waitFor(() => expect(api.notebook.rateMemory).toHaveBeenCalledWith("a", "unsure"));
    expect(api.notebook.rateMemory).toHaveBeenCalledTimes(1);
    expect(api.notebook.setPersonal).not.toHaveBeenCalled();
  });

  it("rates from the front of the card, as Hanzii does", async () => {
    const api = fakes();
    await openFlashcards(api);
    expect(memory("Remembered")).toBeEnabled();
    expect(screen.queryByRole("group", { name: "Can use" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next card" })).not.toBeInTheDocument();
    await userEvent.click(memory("Remembered"));
    await waitFor(() => expect(counter()).toBe("2 / 3"));
  });

  it("shows an error and stays on the card when the waiting rating cannot be sent", async () => {
    const api = fakes();
    api.notebook.rateMemory.mockRejectedValueOnce(new ApiError("network", null, { message: "offline" }));
    await openFlashcards(api);
    await userEvent.click(memory("Remembered"));
    await waitFor(() => expect(counter()).toBe("2 / 3"));
    await userEvent.click(memory("Not yet"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your rating could not be saved");
    expect(counter()).toBe("2 / 3");
    await userEvent.click(memory("Not yet"));
    await waitFor(() => expect(counter()).toBe("3 / 3"));
    expect(api.notebook.rateMemory).toHaveBeenLastCalledWith("a", "remembered");
  });

  it("one step back takes the last rating back, so the card is rated again and sent once", async () => {
    const api = fakes();
    await openFlashcards(api);
    await userEvent.click(memory("Not yet"));
    await waitFor(() => expect(counter()).toBe("2 / 3"));
    expect(screen.getByText("Not yet 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Previous card" }));
    expect(counter()).toBe("1 / 3");
    expect(screen.getByText("Not yet 0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous card" })).toBeDisabled();
    await userEvent.click(memory("Remembered"));
    await userEvent.click(memory("Unsure"));
    await waitFor(() => expect(counter()).toBe("3 / 3"));
    expect(api.notebook.rateMemory.mock.calls).toEqual([["a", "remembered"]]);
  });

  it("sends the last rating when the deck ends and when the page is left", async () => {
    const api = fakes();
    const view = await openFlashcards(api);
    await userEvent.click(memory("Remembered"));
    await userEvent.click(memory("Unsure"));
    await userEvent.click(memory("Not yet"));
    await waitFor(() => expect(api.notebook.rateMemory).toHaveBeenCalledWith("c", "not_yet"));
    expect(api.notebook.rateMemory).toHaveBeenCalledTimes(3);
    view.unmount();
    expect(api.notebook.rateMemory).toHaveBeenCalledTimes(3);

    const again = fakes();
    const second = await openFlashcards(again);
    await userEvent.click(memory("Unsure"));
    second.unmount();
    expect(again.notebook.rateMemory).toHaveBeenCalledWith("a", "unsure", true);
  });

  it("treats a swipe as the matching Memory rating", async () => {
    const api = fakes();
    await openFlashcards(api);
    const card = () => screen.getByTestId("flashcard");
    // jsdom has no PointerEvent, so fireEvent.pointer* would lose clientX.
    const pointer = (type: string, clientX: number) => fireEvent(card(), new MouseEvent(type, { bubbles: true, clientX }));
    const swipe = (to: number) => {
      pointer("pointerdown", 300);
      pointer("pointermove", to);
      pointer("pointerup", to);
    };
    swipe(100);
    await waitFor(() => expect(counter()).toBe("2 / 3"));
    swipe(500);
    await waitFor(() => expect(api.notebook.rateMemory).toHaveBeenCalledWith("a", "not_yet"));
  });

  it("flips from the keyboard and saves favorite and note through the personal marks", async () => {
    const api = fakes();
    await openFlashcards(api);
    screen.getByRole("button", { name: "Show the answer" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Show the word" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Favorite" }));
    await waitFor(() => expect(api.notebook.setPersonal).toHaveBeenCalledWith("a", { favorite: true }));
    await userEvent.click(screen.getByRole("button", { name: "Note" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "gate B");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.notebook.setPersonal).toHaveBeenCalledWith("a", { note: "gate B" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("review setup", () => {
  const list = [word("a", "airport", "san bay"), word("b", "bridge", "cay cau")];
  const han = [word("h", "妈妈", "mẹ", { languageCode: "zh", reading: "mā ma" })];
  const open = (scope = "nb1", preselected = ["a"], words = list) => mount(fakes(), <ReviewSetupSheet scope={scope} words={words} preselected={preselected} onClose={() => undefined} />, "/sheet", "/sheet");
  const flipSwitch = (name: string) => userEvent.click(screen.getByRole("button", { name }));
  const where = () => screen.findByTestId("where");

  it("starts the language's review with the chosen words, Multiple choice and the way back", async () => {
    open();
    await flipSwitch("Start");
    expect((await where()).textContent).toBe("/review/en?types=choice&concepts=a&back=%2Fwords%2Flists%2Fnb1");
  });

  it("mixes the chosen types, and keeps the display choices", async () => {
    open("level-2", ["h"], han);
    await flipSwitch("Match pairs");
    await flipSwitch("Order the sentence");
    await flipSwitch("Pronunciation");
    await flipSwitch("Write the word");
    await flipSwitch("Show the answer right away");
    await flipSwitch("Images");
    await flipSwitch("Start");
    expect((await where()).textContent).toBe(
      "/review/zh?types=choice%2Cmatch%2Corder%2Cspeak%2Cwrite&concepts=h&answer=0&images=0&back=%2Fwords%3Flevel%3D2");
  });

  it("offers Write the word only when the notebook has Chinese or Japanese characters", () => {
    open();
    expect(screen.getByRole("button", { name: "Pronunciation" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Write the word" })).not.toBeInTheDocument();
  });

  it("says which types move the schedule and which are practice only", () => {
    open();
    expect(screen.getByRole("heading", { name: "Counts toward your schedule" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Practice only" })).toBeInTheDocument();
  });

  it("cannot start with no words or no type", async () => {
    open("nb1", []);
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
    await flipSwitch("Select all");
    expect(screen.getByRole("button", { name: "Start" })).toBeEnabled();
    await flipSwitch("Multiple choice");
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("keeps a chosen list within the server's limit and reads a link back", () => {
    const ids = Array.from({ length: 60 }, (_, i) => `id${i}`);
    const href = reviewHref("en", ids, ["choice"], { showAnswer: true, images: true, reading: true }, "/words/lists");
    const params = new URLSearchParams(href.split("?")[1]);
    expect(readReviewParams(params).conceptIds).toHaveLength(50);
    expect(readReviewParams(new URLSearchParams("types=bogus")).types).toEqual(["choice"]);
    expect(readReviewParams(new URLSearchParams("reading=0")).display).toEqual({ showAnswer: true, images: true, reading: false });
  });
});

const card = (conceptId: string, text: string, exercise: ReviewCard["exercise"]): ReviewCard => ({ conceptId, text, reading: null, isNew: false, exercise });
const result = (conceptId: string, correct: boolean, expected: string, extra: Partial<AnswerResult> = {}): AnswerResult => ({
  conceptId, correct, outcome: correct ? "correct" : "incorrect", grade: correct ? "good" : "again", scheduled: true,
  nextReviewAt: null, expected, duplicate: false, assessment: null, ...extra,
});
const ASSESSMENT: PronunciationAssessment = {
  band: "good", scores: { pronunciation: 82, accuracy: 80, fluency: 90, completeness: 100, prosody: 64 },
  words: [{ word: "airport", accuracy: 74, error_type: "mispronunciation", phonemes: [{ phoneme: "ɛ", accuracy: 95 }, { phoneme: "ɹ", accuracy: 41 }] }],
};

function reviewFakes(cards: ReviewCard[], grade: (request: { conceptId: string; answer: Answer }) => AnswerResult) {
  const api = fakes();
  return {
    ...api,
    review: {
      due: vi.fn(async () => ({ languageCode: "en", dueCount: cards.length, newCount: 0, cards })),
      answer: vi.fn(async (request: { conceptId: string; answer: Answer }) => grade(request)),
      answerPronunciation: vi.fn(async (request: { conceptId: string }) => result(request.conceptId, true, "airport", { scheduled: false, assessment: ASSESSMENT })),
      audioUrl: vi.fn(async () => "blob:card"),
      latestPronunciation: vi.fn(async () => null),
    },
  };
}
const openReview = (api: object, query: string) =>
  mount(api as unknown as Fakes, <PracticeScreen />, `/review/en?${query}`, "/review/:language");

describe("review", () => {
  beforeEach(() => {
    window.HTMLMediaElement.prototype.play = vi.fn(async () => undefined);
    window.HTMLMediaElement.prototype.pause = vi.fn();
  });

  it("asks the server for the chosen words and types, sends the picked option and marks the server's answer", async () => {
    const cards = [card("a", "airport", { type: "choice", text: "airport", reading: null, sentence: null, options: ["san bay", "cay cau", "dam may"] })];
    const api = reviewFakes(cards, (request) => result(request.conceptId, false, "san bay"));
    openReview(api, "types=choice&concepts=a,b&back=%2Fwords%2Flists%2Fnb1");
    await userEvent.click(await screen.findByRole("button", { name: "cay cau" }));
    expect(api.review.due).toHaveBeenCalledWith("en", ["choice", "listening"], ["a", "b"]);
    expect(api.review.answer).toHaveBeenCalledWith(expect.objectContaining({ conceptId: "a", exerciseType: "choice", answer: { option: "cay cau" }, passId: expect.stringMatching(/^pass-/) }));
    expect(await screen.findByText("Not quite · Answer: san bay")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "san bay" })).toHaveClass("good");
    expect(screen.getByRole("button", { name: "cay cau" })).toHaveClass("bad");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("0/1")).toBeInTheDocument();
    expect(screen.getByText("airport")).toBeInTheDocument(); // worth another look
    expect(screen.getByRole("link", { name: "Back to notebook" })).toHaveAttribute("href", "/words/lists/nb1");
  });

  it("hides the right answer when the learner turned that off", async () => {
    const cards = [card("a", "airport", { type: "listening", options: ["airport", "bridge"] })];
    const api = reviewFakes(cards, (request) => result(request.conceptId, false, "airport"));
    openReview(api, "types=choice&answer=0");
    await userEvent.click(await screen.findByRole("button", { name: "Listen" }));
    expect(api.review.audioUrl).toHaveBeenCalledWith("a");
    await userEvent.click(screen.getByRole("button", { name: "bridge" }));
    expect(await screen.findByText("Not quite")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "airport" })).not.toHaveClass("good");
  });

  it("matches pairs on one board, each pairing graded by the server as the meaning chosen for that word", async () => {
    const cards = [
      card("a", "airport", { type: "match", text: "airport", reading: null, meaning: "san bay" }),
      card("b", "bridge", { type: "match", text: "bridge", reading: null, meaning: "cay cau" }),
    ];
    const meanings: Record<string, string> = { a: "san bay", b: "cay cau" };
    const api = reviewFakes(cards, (request) => result(request.conceptId, (request.answer as { option: string }).option === meanings[request.conceptId], meanings[request.conceptId]));
    openReview(api, "types=match");
    expect(await screen.findByText("1/1")).toBeInTheDocument();
    const words = screen.getByRole("group", { name: "Words" });
    const right = screen.getByRole("group", { name: "Meanings" });
    await userEvent.click(within(words).getByRole("button", { name: "airport" }));
    await userEvent.click(within(right).getByRole("button", { name: "cay cau" }));
    expect(await screen.findByText(/do not match/)).toBeInTheDocument();
    for (const [left, meaning] of [["airport", "san bay"], ["bridge", "cay cau"]]) {
      await userEvent.click(within(words).getByRole("button", { name: left }));
      await userEvent.click(within(right).getByRole("button", { name: meaning }));
    }
    expect(api.review.answer.mock.calls.map(([request]) => [request.conceptId, (request as unknown as { exerciseType: string }).exerciseType, request.answer]))
      .toEqual([["a", "match", { option: "cay cau" }], ["a", "match", { option: "san bay" }], ["b", "match", { option: "cay cau" }]]);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("1/2")).toBeInTheDocument();
  });

  it("puts a sentence in order and sends it joined", async () => {
    const cards = [card("a", "airport", { type: "order", kind: "sentence", parts: ["big", "The", "airport", "is"], meaning: "san bay" })];
    const api = reviewFakes(cards, (request) => result(request.conceptId, true, "The airport is big"));
    openReview(api, "types=order");
    const bank = await screen.findByTestId("order-bank");
    expect(screen.getByRole("button", { name: "Check" })).toBeDisabled();
    for (const part of ["The", "airport", "is", "big"]) await userEvent.click(within(bank).getByRole("button", { name: part }));
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("Correct")).toBeInTheDocument();
    expect(api.review.answer).toHaveBeenCalledWith(expect.objectContaining({ exerciseType: "order", answer: { text: "The airport is big" } }));
  });

  it("writes the word and says on the summary that writing and pronunciation do not move the schedule", async () => {
    const cards = [card("a", "机场", { type: "writing", script: "strokes", characters: "机场", reading: "jī chǎng", meaning: "san bay" })];
    const api = reviewFakes(cards, (request) => result(request.conceptId, true, "机场", { scheduled: false }));
    openReview(api, "types=write");
    await userEvent.type(await screen.findByRole("textbox", { name: "Type the word" }), "机场");
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("Correct")).toBeInTheDocument();
    expect(api.review.answer).toHaveBeenCalledWith(expect.objectContaining({ exerciseType: "writing", answer: { text: "机场" } }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Pronunciation and writing are practice: they do not change your review schedule.")).toBeInTheDocument();
  });

  it("says plainly when there is nothing to review", async () => {
    openReview(reviewFakes([], () => result("x", true, "x")), "types=order");
    expect(await screen.findByText("Nothing to review this way right now.")).toBeInTheDocument();
  });

  it("gathers match cards into boards of up to four, a last single pair joining the board before", () => {
    const match = (id: string) => card(id, id, { type: "match", text: id, reading: null, meaning: `m-${id}` });
    const other = card("x", "x", { type: "listening", options: ["x", "y"] });
    const items = reviewItems([match("1"), other, match("2"), match("3"), match("4"), match("5")], () => 0);
    expect(items.map((item) => (item.kind === "match" ? item.cards.map((entry) => entry.conceptId).join("") : item.id))).toEqual(["12345", "x"]);
    expect(serverTypes(["choice", "speak"])).toEqual(["choice", "listening", "pronunciation"]);
  });
});

describe("pronunciation", () => {
  const list = [word("a", "airport", "san bay"), word("b", "bridge", "cay cau")];
  const recorder = (seconds = 1) => ({ takeChunk: vi.fn(), stop: vi.fn(() => new Int16Array(16_000 * seconds)), dispose: vi.fn() });
  const speakFakes = () => reviewFakes([], () => result("x", true, "x"));

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:attempt");
    URL.revokeObjectURL = vi.fn();
  });

  it("stops the microphone when the dialog closes", async () => {
    const mic = recorder();
    vi.mocked(startPcmRecorder).mockResolvedValue(mic);
    const onClose = vi.fn();
    mount(speakFakes() as unknown as Fakes, <PronounceDialog words={list} onClose={onClose} />, "/p", "/p");
    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await screen.findByRole("button", { name: "Stop recording" });
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(mic.dispose).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("stops the microphone on unmount and when Escape closes it", async () => {
    const mic = recorder();
    vi.mocked(startPcmRecorder).mockResolvedValue(mic);
    const onClose = vi.fn();
    const view = mount(speakFakes() as unknown as Fakes, <PronounceDialog words={list} onClose={onClose} />, "/p", "/p");
    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await screen.findByRole("button", { name: "Stop recording" });
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
    expect(mic.dispose).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(mic.dispose.mock.calls.length).toBeGreaterThanOrEqual(1);
  });

  it("assesses the saved word by id and shows every Azure score, each sound and the replay", async () => {
    vi.mocked(startPcmRecorder).mockResolvedValue(recorder());
    const api = speakFakes();
    mount(api as unknown as Fakes, <PronounceDialog words={list} initialIndex={1} onClose={() => undefined} />, "/p", "/p");
    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop recording" }));
    const shown = await screen.findByRole("region", { name: "Pronunciation result" });
    expect(within(shown).getByRole("img", { name: "Pronunciation 82 out of 100" })).toBeInTheDocument();
    expect(within(shown).getByText("Good job")).toBeInTheDocument();
    for (const name of ["Accuracy", "Fluency", "Completeness", "Intonation"]) expect(within(shown).getByText(name)).toBeInTheDocument();
    expect(within(shown).getByText("Mispronounced · 74/100")).toBeInTheDocument();
    expect(within(shown).getByText("ɹ")).toBeInTheDocument();
    expect(api.review.answerPronunciation).toHaveBeenCalledWith(expect.objectContaining({ conceptId: "b", languageCode: "en", passId: null }), expect.any(Blob));
    expect(screen.getByRole("button", { name: "Replay your attempt" })).toBeEnabled();
  });

  it("shows the word's latest stored result before a new attempt", async () => {
    const api = speakFakes();
    api.review.latestPronunciation.mockResolvedValue({ score: 82, band: "good", at: "2026-11-13T10:00:00Z", assessment: ASSESSMENT } as never);
    mount(api as unknown as Fakes, <PronounceDialog words={list} onClose={() => undefined} />, "/p", "/p");
    expect(await screen.findByText(/Your latest result/)).toBeInTheDocument();
    expect(api.review.latestPronunciation).toHaveBeenCalledWith("a");
  });

  it("explains a missing voice consent", async () => {
    vi.mocked(startPcmRecorder).mockResolvedValue(recorder());
    const api = speakFakes();
    api.review.answerPronunciation.mockRejectedValueOnce(new ApiError("conflict", 409, { code: "voice_consent_required" }));
    mount(api as unknown as Fakes, <PronounceDialog words={list} onClose={() => undefined} />, "/p", "/p");
    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop recording" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Allow voice processing");
  });
});

describe("word audio", () => {
  it("reads a saved word by its id when the dictionary has no audio for it", async () => {
    const api = reviewFakes([], () => result("x", true, "x"));
    api.notebook.audioUrl.mockRejectedValueOnce(new ApiError("not_found", 404, { code: "word_not_in_dictionary" }));
    window.HTMLMediaElement.prototype.play = vi.fn(async () => undefined);
    mount(api as unknown as Fakes, <PronounceDialog words={[word("a", "book club", "câu lạc bộ sách")]} onClose={() => undefined} />, "/p", "/p");
    await userEvent.click(screen.getByRole("button", { name: "Listen" }));
    await waitFor(() => expect(api.review.audioUrl).toHaveBeenCalledWith("a"));
    expect(screen.queryByText("Audio is not available for this word.")).not.toBeInTheDocument();
  });
});

describe("writing", () => {
  const zh = [
    { ...listWord("a", "妈妈", "me"), reading: "mā ma" },
    { ...listWord("b", "狗", "con cho"), reading: "gǒu" },
  ];
  const zhFakes = () => {
    const api = reviewFakes([], (request) => result(request.conceptId, true, "妈妈", { scheduled: false }));
    api.lists.detail.mockResolvedValue({ id: "nb1", languageCode: "zh", name: "Han", words: zh, waiting: [] } as never);
    return api;
  };
  const writer = () => ({
    quiz: vi.fn(async (options: { onComplete?: () => void }) => { hanzi.options = options as never; }),
    cancelQuiz: vi.fn(), hideCharacter: vi.fn(), hideOutline: vi.fn(), showOutline: vi.fn(), animateCharacter: vi.fn(),
  });
  const open = (api: object) => mount(api as unknown as Fakes, <WritingScreen />, "/notebook/nb1/writing", "/notebook/:scope/writing");

  afterEach(() => hanzi.create.mockReset());

  it("starts a stroke quiz on the first character and restarts it with the eraser", async () => {
    const active = writer();
    hanzi.create.mockReturnValue(active);
    open(zhFakes());
    await waitFor(() => expect(active.quiz).toHaveBeenCalledTimes(1));
    expect(hanzi.create.mock.calls[0][1]).toBe("妈");
    await userEvent.click(screen.getByRole("button", { name: "Erase" }));
    expect(active.quiz).toHaveBeenCalledTimes(2);
  });

  it("shows one tile per character with its reading, and a tile switches the character", async () => {
    const active = writer();
    hanzi.create.mockReturnValue(active);
    open(zhFakes());
    await waitFor(() => expect(active.quiz).toHaveBeenCalledTimes(1));
    const tiles = document.querySelectorAll(".st-wr-list button");
    expect([...tiles].map((tile) => tile.textContent)).toEqual(["mā妈", "gǒu狗"]);
    expect(tiles[0]).toHaveAttribute("aria-current", "true");
    await userEvent.click(tiles[1]);
    await waitFor(() => expect(hanzi.create).toHaveBeenCalledTimes(2));
    expect(hanzi.create.mock.calls[1][1]).toBe("狗");
    expect(document.querySelector(".st-wr-list button[aria-current]")?.textContent).toBe("gǒu狗");
    await userEvent.type(screen.getByRole("textbox", { name: "Find a character" }), "mā");
    expect([...document.querySelectorAll(".st-wr-list button")].map((tile) => tile.textContent)).toEqual(["mā妈"]);
  });

  it("says it is finished and sends the word with its mistakes once every character is written", async () => {
    const active = writer();
    hanzi.create.mockReturnValue(active);
    const api = zhFakes();
    open(api);
    await waitFor(() => expect(active.quiz).toHaveBeenCalledTimes(1));
    hanzi.options!.onComplete({ totalMistakes: 2 });
    expect(await screen.findByText(/Every stroke/)).toBeInTheDocument();
    await waitFor(() => expect(api.review.answer).toHaveBeenCalledWith(expect.objectContaining({
      conceptId: "a", languageCode: "zh", exerciseType: "writing", passId: null, answer: { text: "妈妈", mistakes: 2 }, hintUsed: false })));
    expect(api.review.answer).toHaveBeenCalledTimes(1);
  });

  it("offers a retry when a character's data cannot be loaded", async () => {
    let failLoad: () => void = () => undefined;
    hanzi.create.mockImplementation((_host: HTMLElement, _character: string, options: { onLoadCharDataError: () => void }) => {
      failLoad = options.onLoadCharDataError;
      return writer();
    });
    open(zhFakes());
    await waitFor(() => expect(hanzi.create).toHaveBeenCalledTimes(1));
    failLoad();
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(hanzi.create).toHaveBeenCalledTimes(2));
  });

  it("has no writing practice for English words", async () => {
    const api = reviewFakes([], (request) => result(request.conceptId, true, "airport", { scheduled: false }));
    open(api);
    expect(await screen.findByText("This notebook has no Chinese or Japanese characters to write.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(hanzi.create).not.toHaveBeenCalled();
    expect(api.review.answer).not.toHaveBeenCalled();
  });
});
