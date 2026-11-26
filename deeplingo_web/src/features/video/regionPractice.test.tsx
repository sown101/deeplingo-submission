import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentPanelContext, type AgentLauncherContext } from "../../app/AgentPanelContext";
import { ContainerProvider, type AppContainer } from "../../app/container";
import type { TranscriptSegmentView } from "../../lib/api/dto";
import { WatchScreen } from "./WatchScreen";

vi.mock("../../app/AuthProvider", () => ({ useAuth: () => ({ signOut: vi.fn() }) }));
beforeEach(() => vi.stubGlobal("scrollTo", vi.fn()));
afterEach(() => { vi.unstubAllGlobals(); window.getSelection()?.removeAllRanges(); });

const LIB = "aaaaaaaa-2222-3333-4444-555555555555";
const TRACK = "bbbbbbbb-2222-3333-4444-555555555555";
const seg = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const segment = (n: number, translation: string | null): TranscriptSegmentView => ({
  segment_id: seg(n), sequence: n, text: `So I ended up taking a taxi ${n}.`, start_ms: (n - 1) * 4000, end_ms: n * 4000,
  translation: translation ? { language_code: "vi", text: translation } : null, romanizations: [], learning_objects: [],
});
const REGION = { transcript_id: TRACK, start_segment_id: seg(1), end_segment_id: seg(2), start_ms: 0, end_ms: 8000,
  segment_count: 2, preparation: null };
const REGION_ID = `${seg(1)}_${seg(2)}`;

function playbackWith(overrides: Record<string, unknown> = {}) {
  let rows = [segment(1, null), segment(2, null)];
  const playback = {
    getPlayableVideo: vi.fn(async () => ({ library_item_id: LIB, video_id: LIB, provider: "youtube",
      external_video_id: "jNQXAC9IVRw", title: "Taxi talk", language_code: "en", duration_ms: 20_000 })),
    getTranscript: vi.fn(async () => ({ library_item_id: LIB, language_code: "en", translation_language_code: "vi", segments: rows })),
    getWorkspace: vi.fn(async () => ({ library_item_id: LIB, position_ms: null, region: REGION })),
    saveWatchPosition: vi.fn(async () => ({ library_item_id: LIB, position_ms: 0, region: REGION })),
    getParts: vi.fn(async () => ({ transcript_id: TRACK, source: "ai", parts: [{ start_segment_id: seg(1), end_segment_id: seg(2),
      start_ms: 0, end_ms: 8000, segment_count: 2, title: "Taxi" }] })),
    getRegionQuestions: vi.fn(async () => ({ status: "no_region", questions: [] })),
    // The server translates the sentences once; the next transcript read carries the meanings.
    ensureTranslations: vi.fn(async () => { rows = [segment(1, "Vậy là tôi đi taxi 1."), segment(2, "Vậy là tôi đi taxi 2.")]; return 2; }),
    recordLookup: vi.fn(async () => undefined), recordDictation: vi.fn(async () => undefined),
    lookup: vi.fn(async () => { throw new Error("not needed"); }),
    ...overrides,
  };
  return playback;
}

function renderWatch(playback: object, words: object = {}, path = `/library/videos/${LIB}/watch`,
  onLauncherChange?: (launcher: AgentLauncherContext | null) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const watch = <WatchScreen />;
  return render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={{ playback, words, onboarding: { loadProfile: vi.fn(async () => ({ learning_language: "en" })) },
        lists: { list: vi.fn(async () => []) } } as unknown as AppContainer}>
        <MemoryRouter initialEntries={[path]}>
          <Routes><Route path="/library/videos/:libraryItemId/watch" element={onLauncherChange
            ? <AgentPanelContext.Provider value={{ host: null, onPhaseChange: vi.fn(), onLauncherChange }}>{watch}</AgentPanelContext.Provider>
            : watch} /></Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

describe("bilingual subtitles", () => {
  it("translates once on first open, then shows the meaning under each line and can hide it", async () => {
    const playback = playbackWith();
    renderWatch(playback);
    const transcript = await screen.findByRole("region", { name: "Transcript" });
    await waitFor(() => expect(playback.ensureTranslations).toHaveBeenCalledTimes(1));
    expect(playback.ensureTranslations).toHaveBeenCalledWith(LIB);
    const meaning = await within(transcript).findByText("Vậy là tôi đi taxi 1.");
    expect(meaning.getAttribute("lang")).toBe("vi");
    expect(meaning.closest(".transcript-row")?.textContent).toContain("So I ended up taking a taxi 1.");
    fireEvent.click(screen.getByRole("checkbox", { name: "Translation" }));
    expect(within(transcript).queryByText("Vậy là tôi đi taxi 1.")).toBeNull();
    expect(playback.ensureTranslations).toHaveBeenCalledTimes(1);
  });

  it("does not ask for translations when every line already has one", async () => {
    const playback = playbackWith({
      getTranscript: vi.fn(async () => ({ library_item_id: LIB, language_code: "en", translation_language_code: "vi",
        segments: [segment(1, "Một"), segment(2, "Hai")] })),
    });
    renderWatch(playback);
    expect(await screen.findByText("Một")).toBeInTheDocument();
    expect(playback.ensureTranslations).not.toHaveBeenCalled();
  });
});

describe("lookup in a study part", () => {
  it("selecting a phrase looks it up, logs it against the part and saves a word with the part", async () => {
    const lookupView = {
      unit_text: "ended up", unit_start: 5, unit_end: 13, unit_kind: "phrase", selection_start: 5, selection_end: 13,
      selection_is_part: false, headword: "end up", meaning: "kết thúc ở", meaning_provenance: "translated_from_sense",
      sense_id: "s1", pattern: [], pattern_explanation: null, note: null, examples: [], dictionary_gloss: null, source: null,
      reading: null, part_of_speech: null, level: null, context_before: null, context_after: null,
    };
    const playback = playbackWith({ lookup: vi.fn(async () => lookupView) });
    const words = { save: vi.fn(async () => ({ conceptId: "c1" })) };
    renderWatch(playback, words);
    const transcript = await screen.findByRole("region", { name: "Transcript" });
    const row = within(transcript).getAllByRole("group")[0];
    const range = document.createRange();
    range.setStart(within(row).getByText("ended", { selector: ".word" }).firstChild!, 0);
    range.setEnd(within(row).getByText("up", { selector: ".word" }).firstChild!, 2);
    window.getSelection()!.addRange(range);
    fireEvent.click(row);
    await screen.findByRole("dialog");
    await waitFor(() => expect(playback.recordLookup).toHaveBeenCalledTimes(1));
    expect(playback.recordLookup).toHaveBeenCalledWith(LIB, { id: expect.any(String), segment_id: seg(1),
      span: { start: 5, end: 13 }, region_id: REGION_ID });
    fireEvent.click(await screen.findByRole("button", { name: "Add to my words" }));
    await waitFor(() => expect(words.save).toHaveBeenCalledTimes(1));
    expect(words.save).toHaveBeenCalledWith(expect.objectContaining({ source: "lookup", library_item_id: LIB,
      segment_id: seg(1), region_id: REGION_ID }));
  });
});

describe("practice in a study part", () => {
  it("a Dictation attempt is reported with the part it belongs to", async () => {
    const playback = playbackWith();
    renderWatch(playback);
    fireEvent.click(await screen.findByRole("tab", { name: "Dictation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Hard · type it" }));
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    fireEvent.change(screen.getByLabelText("Type what you hear"), { target: { value: "So I ended up" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(playback.recordDictation).toHaveBeenCalledTimes(1));
    expect(playback.recordDictation).toHaveBeenCalledWith(LIB, expect.objectContaining({ segment_id: seg(1), region_id: REGION_ID }));
  });

  it("the page's Tata launcher talks about the part; the panel has no second Tata button", async () => {
    const onLauncherChange = vi.fn();
    const view = renderWatch(playbackWith(), {}, undefined, onLauncherChange);
    fireEvent.click(await screen.findByRole("tab", { name: "Questions" }));
    await waitFor(() => expect(onLauncherChange).toHaveBeenLastCalledWith({
      title: "Talk about part 1", subtitle: "Tata knows what you are practising", segmentId: seg(1) }));
    expect(screen.queryByRole("link", { name: /Tata/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Part result" })).toBeInTheDocument();
    view.unmount();
    expect(onLauncherChange).toHaveBeenLastCalledWith(null);
  });

  it("the part result opens in the practice panel and a tab closes it", async () => {
    const playback = playbackWith({ getRegionResult: vi.fn(async () => ({ region_id: REGION_ID, practised: false,
      dictation_attempts: 0, dictation_sentences: 0, dictation_accuracy: null, shadowing_attempts: 0, shadowing_sentences: 0,
      shadowing_average: null, questions_answered: 0, questions_correct: 0, lookups: 0, words_saved: 0 })) });
    renderWatch(playback);
    fireEvent.click(await screen.findByRole("tab", { name: "Questions" }));
    fireEvent.click(await screen.findByRole("button", { name: "Part result" }));
    const result = await screen.findByRole("region", { name: "Result for 00:00–00:08" });
    expect(result.closest(".watch-right")).not.toBeNull();
    expect(await within(result).findByText("Nothing practised in this part yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(screen.queryByRole("region", { name: "Result for 00:00–00:08" })).toBeNull();
    expect(screen.getByRole("region", { name: "Transcript" })).toBeVisible();
  });
});
