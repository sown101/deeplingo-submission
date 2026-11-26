import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../../app/container";
import { ApiError } from "../../../lib/api/errors";
import type { TranscriptSegmentView } from "../../../lib/api/dto";
import { QuestionsPanel } from "./QuestionsPanel";
import { parseQuestionAnswer, parseRegionQuestions } from "./questionModels";

const LIB = "11111111-1111-4111-8111-111111111111";
const QUESTION = "22222222-2222-4222-8222-222222222222";
const SEGMENT = "33333333-3333-4333-8333-333333333333";

const segment: TranscriptSegmentView = {
  segment_id: SEGMENT, sequence: 1, start_ms: 4000, end_ms: 7000,
  text: "So I ended up taking a taxi.", translation: null, romanizations: [], learning_objects: [],
} as TranscriptSegmentView;

const ready = {
  status: "ready",
  questions: [{ id: QUESTION, position: 1, question: "Người nói đi bằng gì?", options: ["Taxi", "Xe buýt", "Tàu", "Xe đạp"] }],
};

function answerFor(selected: number) {
  return {
    question_id: QUESTION, selected_option: selected, correct: selected === 0, correct_index: 0,
    evidence_segment_id: SEGMENT, evidence_quote: "taking a taxi", explanation: "Câu nói 'taking a taxi'.",
  };
}

function renderPanel(playback: object, onPlay = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={{ playback } as unknown as AppContainer}>
        <QuestionsPanel libraryItemId={LIB} regionKey="r" segments={[segment]} languageCode="en" onPlaySentence={onPlay} />
      </ContainerProvider>
    </QueryClientProvider>,
  );
  return onPlay;
}

describe("region question parsing", () => {
  it("accepts questions without answers and rejects malformed or foreign responses", () => {
    expect(parseRegionQuestions(ready).questions[0].options).toHaveLength(4);
    expect(() => parseRegionQuestions({ status: "done", questions: [] })).toThrow();
    expect(() => parseRegionQuestions({ status: "none", questions: ready.questions })).toThrow();
    expect(() => parseRegionQuestions({ ...ready, questions: [{ ...ready.questions[0], options: ["a", "b"] }] })).toThrow();
    expect(parseQuestionAnswer(answerFor(0), QUESTION).correct).toBe(true);
    expect(() => parseQuestionAnswer(answerFor(0), SEGMENT)).toThrow();
    expect(() => parseQuestionAnswer({ ...answerFor(0), correct_index: 4 }, QUESTION)).toThrow();
  });
});

describe("QuestionsPanel", () => {
  it("sends only the chosen option and shows the server's check with its quote", async () => {
    const playback = {
      getRegionQuestions: vi.fn().mockResolvedValue(parseRegionQuestions(ready)),
      answerRegionQuestion: vi.fn(async (_lib: string, _q: string, body: { selected_option: number }) =>
        parseQuestionAnswer(answerFor(body.selected_option), QUESTION)),
    };
    const onPlay = renderPanel(playback);
    fireEvent.click(await screen.findByRole("button", { name: "Xe buýt" }));
    await screen.findByText(/Not quite/);
    const [lib, question, body] = playback.answerRegionQuestion.mock.calls[0];
    expect([lib, question]).toEqual([LIB, QUESTION]);
    expect(Object.keys(body).sort()).toEqual(["id", "selected_option"]);
    expect(body.selected_option).toBe(1);
    expect(screen.getByText("taking a taxi")).toHaveAttribute("lang", "en");
    expect(screen.getByRole("button", { name: "Taxi" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Play this sentence" }));
    expect(onPlay).toHaveBeenCalledWith(segment);
  });

  it("retries a failed check with the same event id", async () => {
    const playback = {
      getRegionQuestions: vi.fn().mockResolvedValue(parseRegionQuestions(ready)),
      answerRegionQuestion: vi.fn()
        .mockRejectedValueOnce(new ApiError("server", 503, {}))
        .mockResolvedValueOnce(parseQuestionAnswer(answerFor(0), QUESTION)),
    };
    renderPanel(playback);
    fireEvent.click(await screen.findByRole("button", { name: "Taxi" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Taxi" }));
    await screen.findByText("Right.");
    const [first, second] = playback.answerRegionQuestion.mock.calls.map((call) => call[2].id);
    expect(first).toBe(second);
  });

  it.each([
    ["no_region", /Choose a study part/],
    ["preparing", /being prepared/],
    ["none", /no questions for this part/],
    ["unavailable", /not available for this part/],
  ])("explains the %s state", async (status, text) => {
    const playback = { getRegionQuestions: vi.fn().mockResolvedValue({ status, questions: [] }), answerRegionQuestion: vi.fn() };
    renderPanel(playback);
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(playback.answerRegionQuestion).not.toHaveBeenCalled();
  });

  it("offers to load again when the questions cannot be read", async () => {
    const playback = {
      getRegionQuestions: vi.fn().mockRejectedValueOnce(new ApiError("server", 503, {})).mockResolvedValue(parseRegionQuestions(ready)),
      answerRegionQuestion: vi.fn(),
    };
    renderPanel(playback);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Taxi" })).toBeInTheDocument());
  });
});
