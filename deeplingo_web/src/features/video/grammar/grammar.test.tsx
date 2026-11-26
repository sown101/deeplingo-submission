import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../../app/container";
import type { ApiClient } from "../../../lib/api/apiClient";
import { ApiError } from "../../../lib/api/errors";
import { PlaybackApi } from "../playbackApi";
import { WatchScreen } from "../WatchScreen";
import { parseVideoTranscriptView } from "../videoModels";
import { GrammarSheet } from "./GrammarSheet";
import { parseGrammarView, type GrammarScope, type GrammarView } from "./grammarModels";

vi.mock("../../companion/CompanionConversation", () => ({ CompanionConversation: () => <div>Companion</div> }));
const ITEM = "11111111-1111-4111-8111-111111111111", SEG = "22222222-2222-4222-8222-222222222222";
const OCC = "33333333-3333-4333-8333-333333333333";
const view: GrammarView = { segment_id: SEG, scope: "selection", source_text: "am", support_language_code: "vi",
  source: "ai_unverified", explanation: {
    sentence_structure: { title: "Cấu trúc câu", text: "Chủ ngữ + to be + tính từ." },
    grammar: { title: "Ngữ pháp", text: "Dùng am với I." },
    important_words: { title: "Từ và cụm quan trọng", text: "happy: vui." },
  } };
const segment = { segment_id: SEG, sequence: 1, text: "I am happy.", start_ms: 0, end_ms: 3000,
  translation: null, romanizations: [], learning_objects: [
    { learning_object_id: OCC, start_codepoint: 2, end_codepoint: 4, grammar_key: "en.be_present" },
  ] };
function wrapper(playback: object, children: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ContainerProvider container={{ playback, companion: {} } as unknown as AppContainer}>
      {children}
    </ContainerProvider>
  </QueryClientProvider>;
}

describe("Transcript grammar", () => {
  it("shows three ordered sections and the unverified label; whole-sentence is explicit", async () => {
    const explainGrammar = vi.fn(async (_item: string, _segment: string, _span: unknown, scope: GrammarScope) => ({
      ...view, scope, source_text: scope === "sentence" ? "I am happy." : "am",
    }));
    const onClose = vi.fn();
    render(wrapper({ explainGrammar }, <GrammarSheet libraryItemId={ITEM} segmentId={SEG} span={{ start: 2, end: 4 }}
      initialScope="selection" supportLanguage="vi" onClose={onClose} />));
    expect(await screen.findByText("AI explanation, unverified")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 3 }).map(item => item.textContent)).toEqual([
      "Cấu trúc câu", "Ngữ pháp", "Từ và cụm quan trọng",
    ]);
    expect(explainGrammar).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Analyse the whole sentence" }));
    expect(await screen.findByText("I am happy.")).toBeInTheDocument();
    expect(explainGrammar).toHaveBeenLastCalledWith(ITEM, SEG, { start: 2, end: 4 }, "sentence");
    await userEvent.click(screen.getByRole("button", { name: "Close grammar explanation" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("sends only positions and scope on the approved endpoint", async () => {
    const client = { post: vi.fn(async () => view) };
    const api = new PlaybackApi(client as unknown as ApiClient);
    await api.explainGrammar(ITEM, SEG, { start: 2, end: 4 }, "selection");
    expect(client.post).toHaveBeenCalledWith(`/learner/me/library/videos/${ITEM}/grammar-explanations`, {
      segment_id: SEG, start_codepoint: 2, end_codepoint: 4, scope: "selection",
    });
  });

  it("keeps grammar annotation metadata and rejects malformed or falsely verified responses", () => {
    const parsed = parseVideoTranscriptView({ library_item_id: ITEM, language_code: "en", translation_language_code: "vi", segments: [segment] });
    expect(parsed.segments[0].learning_objects[0].grammar_key).toBe("en.be_present");
    expect(() => parseGrammarView({ ...view, source: "verified" }, SEG, "selection")).toThrow(ApiError);
    expect(() => parseGrammarView({ ...view, segment_id: OCC }, SEG, "selection")).toThrow(ApiError);
    expect(() => parseGrammarView({ ...view, explanation: {} }, SEG, "selection")).toThrow(ApiError);
  });

  it("opening Watch calls no grammar API; tapping a grammar annotation does not look up or record a word", async () => {
    const playback = {
      getPlayableVideo: vi.fn(async () => ({ library_item_id: ITEM, video_id: ITEM, provider: "youtube", external_video_id: "jNQXAC9IVRw",
        title: "Grammar video", language_code: "en", duration_ms: 3000 })),
      getTranscript: vi.fn(async () => ({ library_item_id: ITEM, language_code: "en", translation_language_code: "vi", segments: [segment] })),
      getWorkspace: vi.fn(async () => ({ library_item_id: ITEM, position_ms: null, region: null })),
      saveWatchPosition: vi.fn(async () => ({ library_item_id: ITEM, position_ms: 0, region: null })),
      getRegionQuestions: vi.fn(async () => ({ status: "no_region", questions: [] })),
      lookup: vi.fn(), recordLookup: vi.fn(), getConcept: vi.fn(),
      explainGrammar: vi.fn(async () => ({ ...view, source: "curriculum_draft" as const })),
    };
    render(wrapper(playback, <MemoryRouter initialEntries={[`/library/videos/${ITEM}/watch`]}>
      <Routes><Route path="/library/videos/:libraryItemId/watch" element={<WatchScreen />} /></Routes>
    </MemoryRouter>));
    const transcript = await screen.findByRole("region", { name: "Transcript" });
    expect(playback.explainGrammar).not.toHaveBeenCalled();
    await userEvent.click(within(transcript).getByRole("button", { name: "am" }));
    expect(await screen.findByText("Prepared content, not yet approved")).toBeInTheDocument();
    await waitFor(() => expect(playback.explainGrammar).toHaveBeenCalledWith(ITEM, SEG, { start: 2, end: 4 }, "selection"));
    expect(playback.lookup).not.toHaveBeenCalled();
    expect(playback.recordLookup).not.toHaveBeenCalled();
    expect(playback.getConcept).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Close grammar explanation" }));
    expect(screen.queryByLabelText("When selecting text")).not.toBeInTheDocument();
    const range = document.createRange();
    range.selectNodeContents(within(transcript).getByText("happy", { selector: ".word" }).firstChild!);
    window.getSelection()?.removeAllRanges(); window.getSelection()?.addRange(range);
    await userEvent.click(within(transcript).getByRole("button", { name: /^Analyse sentence$/ }));
    await waitFor(() => expect(playback.explainGrammar).toHaveBeenLastCalledWith(ITEM, SEG, { start: 5, end: 10 }, "selection"));
    expect(playback.lookup).not.toHaveBeenCalled();
    expect(playback.recordLookup).not.toHaveBeenCalled();
  });
});
