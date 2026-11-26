import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { GrammarShelf } from "../words/GrammarShelf";
import { ReviewDecks } from "./ReviewDecks";
import { parseAnswer, parseDecks, parseDue, parseExercise, parseLatestPronunciation } from "./reviewModels";

function mount(container: object, ui: React.ReactNode, entry = "/words/lists", path = "/words/lists") {
  return render(<MemoryRouter initialEntries={[entry]}>
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ContainerProvider container={container as unknown as AppContainer}>
        <Routes><Route path={path} element={ui} /><Route path="*" element={<output>elsewhere</output>} /></Routes>
      </ContainerProvider>
    </QueryClientProvider>
  </MemoryRouter>);
}

const ASSESSMENT = {
  band: "good", recognized_text: "Book.",
  scores: { pronunciation: 84.4, accuracy: 80, fluency: 90, completeness: 100, prosody: 71 },
  words: [{ word: "book", accuracy: 80, error_type: "mispronunciation", phonemes: [{ phoneme: "b", accuracy: 99 }, { phoneme: "ʊ", accuracy: 42 }] }],
};

describe("review models", () => {
  it("parses every exercise type of the notebook review and rejects a malformed one", () => {
    const types = [
      { type: "choice", prompt: { text: "table", reading: null, sentence: null, options: ["cái bàn", "dòng sông"] } },
      { type: "listening", prompt: { options: ["apple", "river"] } },
      { type: "match", prompt: { text: "leave", reading: null, meaning: "rời đi" } },
      { type: "order", prompt: { kind: "sentence", parts: ["now", "I", "leave"], meaning: "rời đi" } },
      { type: "pronunciation", prompt: { text: "garden", reading: null, meaning: "khu vườn" } },
      { type: "writing", prompt: { script: "strokes", characters: "你好", reading: "nǐ hǎo", meaning: null } },
    ];
    expect(types.map((raw) => parseExercise(raw).type)).toEqual(["choice", "listening", "match", "order", "pronunciation", "writing"]);
    expect(() => parseExercise({ type: "order", prompt: { kind: "sentence", parts: ["one"] } })).toThrow();
    expect(() => parseExercise({ type: "cloze", prompt: { sentence: "x ____" } })).toThrow();
    expect(() => parseDue({ language_code: "en", due_count: 0, new_count: 0, cards: [{ concept_id: "c1" }] })).toThrow();
    expect(() => parseDecks({ decks: [{ language_code: "en", due_count: -1, new_count: 0, total_count: 0 }] })).toThrow();
  });

  it("keeps Azure's whole result on a pronunciation answer and on the latest result of a word", () => {
    const raw = { concept_id: "c1", correct: true, outcome: "correct", grade: "good", scheduled: false,
      next_review_at: null, expected: "book", duplicate: false, assessment: ASSESSMENT };
    const answer = parseAnswer(raw, "c1");
    expect(answer.assessment?.scores.prosody).toBe(71);
    expect(answer.assessment?.words[0].phonemes[1]).toEqual({ phoneme: "ʊ", accuracy: 42 });
    expect(() => parseAnswer({ ...raw, assessment: { ...ASSESSMENT, band: "great" } }, "c1")).toThrow();
    const { band: _band, recognized_text: _text, ...stored } = ASSESSMENT;
    const latest = parseLatestPronunciation({ concept_id: "c1", latest: { score: 84.4, band: "good", occurred_at: "2026-11-14T10:00:00Z", assessment: stored } }, "c1");
    expect(latest?.assessment?.words[0].error_type).toBe("mispronunciation");
    expect(parseLatestPronunciation({ concept_id: "c1", latest: null }, "c1")).toBeNull();
    expect(() => parseLatestPronunciation({ concept_id: "c2", latest: null }, "c1")).toThrow();
  });
});

describe("decks and grammar in the notebook", () => {
  it("shows one deck per language with what is due", async () => {
    const review = { decks: vi.fn(async () => [{ languageCode: "en", dueCount: 3, newCount: 2, totalCount: 9 }, { languageCode: "zh", dueCount: 1, newCount: 0, totalCount: 4 }]) };
    mount({ review }, <ReviewDecks />);
    const deck = await screen.findByRole("link", { name: "Review 中文: 1 due, 0 new" });
    expect(deck).toHaveAttribute("href", "/review/zh");
    expect(screen.getByRole("link", { name: "Review English: 3 due, 2 new" })).toHaveAttribute("href", "/review/en");
  });

  it("lists the agent's redo requests and closes one with a correct answer", async () => {
    const exercise = { id: "en.a1.be.1", grammarKey: "en.a1.be", prompt: "She ___ a teacher.", options: [{ id: "a", text: "is" }, { id: "b", text: "are" }] };
    const review = {
      grammar: vi.fn(async () => ({ languageCode: "en", levels: ["A1"], level: "A1", topics: [{ key: "t", title: "Verbs" }],
        points: [{ key: "en.a1.be", title: "To be", topicKey: "t", lesson: null, exerciseCount: 1, attempts: 0, correctCount: 0, incorrectCount: 0, lessonLearnedAt: null }],
        redo: [{ requestId: "r1", grammarKey: "en.a1.be", title: "To be", level: "A1", reason: "Said “she are”" }] })),
      grammarExercises: vi.fn(async () => [exercise]),
      grammarAnswer: vi.fn(async () => ({ exerciseId: exercise.id, correct: true, correctOptionId: "a", explanation: "She is.", redoClosed: 1 })),
    };
    mount({ review }, <GrammarShelf toggle={null} language="en" />);
    const redo = await screen.findByRole("region", { name: "To redo" });
    expect(within(redo).getByText("Said “she are”")).toBeInTheDocument();
    await userEvent.click(within(redo).getByRole("button", { name: "Redo" }));
    expect(review.grammarExercises).toHaveBeenCalledWith("en", { grammarKey: "en.a1.be" });
    await userEvent.click(await screen.findByRole("radio", { name: "is" }));
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("Removed from your redo list.")).toBeInTheDocument();
    expect(review.grammarAnswer).toHaveBeenCalledWith("en", exercise, "a", expect.any(String));
  });
});
