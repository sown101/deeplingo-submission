import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { WatchScreen } from "../video/WatchScreen";

const WATCH = "/library/videos/:libraryItemId/watch";
import { parseShadowingAssessment } from "./speakingModels";
import { shadowingPayload } from "../../test/speakingFixtures";

const recorder = vi.hoisted(() => ({
  startPcmRecorder: vi.fn(),
}));

vi.mock("../../lib/audio/pcmRecorder", async () => {
  const actual = await vi.importActual<typeof import("../../lib/audio/pcmRecorder")>("../../lib/audio/pcmRecorder");
  return { ...actual, startPcmRecorder: recorder.startPcmRecorder };
});

function fakeRecorder(samples = 16_000) {
  return {
    takeChunk: vi.fn(() => new Int16Array(samples)),
    stop: vi.fn(() => new Int16Array(samples * 2)),
    dispose: vi.fn(),
  };
}

const LIB = "aaaaaaaa-2222-3333-4444-555555555555";
const SEGMENT = shadowingPayload.segment_id;

function renderWithContainer(container: Partial<AppContainer>, path: string, route: string, element: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={container as AppContainer}>
        <MemoryRouter initialEntries={[path]}>
          <Routes><Route path={route} element={element} /></Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  recorder.startPcmRecorder.mockReset();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:attempt"), revokeObjectURL: vi.fn() }));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Shadowing on the watch page", () => {
  function container(assess = vi.fn().mockResolvedValue(parseShadowingAssessment(shadowingPayload, SEGMENT))) {
    return {
      playback: {
        getPlayableVideo: vi.fn().mockResolvedValue({
          library_item_id: LIB, video_id: LIB, provider: "youtube", external_video_id: "jNQXAC9IVRw",
          title: "Autumn words", language_code: "en", duration_ms: 60_000,
        }),
        getTranscript: vi.fn().mockResolvedValue({
          library_item_id: LIB, language_code: "en", translation_language_code: "vi",
          segments: [{
            segment_id: SEGMENT, sequence: 1, text: "Before the leaves fall.", start_ms: 1000, end_ms: 4000,
            translation: { language_code: "vi", text: "Trước khi lá rụng." }, romanizations: [], learning_objects: [],
          }],
        }),
        getWorkspace: vi.fn().mockResolvedValue({ library_item_id: LIB, position_ms: null, region: null }),
        saveWatchPosition: vi.fn().mockResolvedValue({ library_item_id: LIB, position_ms: null, region: null }),
      },
      speaking: { assessShadowing: assess },
    } as unknown as Partial<AppContainer>;
  }

  it("records one sentence and shows server feedback without local grading", async () => {
    const rec = fakeRecorder();
    recorder.startPcmRecorder.mockResolvedValue(rec);
    const deps = container();
    renderWithContainer(deps, `/library/videos/${LIB}/watch?mode=shadowing`, WATCH, <WatchScreen />);

    // The sentence shows in the practice panel and in the sentence list.
    expect((await screen.findAllByText("Before the leaves fall.")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Record" }));
    fireEvent.click(await screen.findByRole("button", { name: /Stop/ }));

    expect(await screen.findByText("Good job")).toBeInTheDocument();
    const speaking = deps.speaking as unknown as { assessShadowing: ReturnType<typeof vi.fn> };
    expect(speaking.assessShadowing).toHaveBeenCalledWith(LIB, SEGMENT, expect.any(Int16Array), undefined);
    expect(screen.getByRole("img", { name: "Pronunciation 82 out of 100" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "leaves" }));
    expect(screen.getAllByRole("status").some(status => status.textContent?.includes("Mispronounced"))).toBe(true);
  });

  it("explains a blocked microphone and never uploads", async () => {
    const { MicrophoneError } = await import("../../lib/audio/pcmRecorder");
    recorder.startPcmRecorder.mockRejectedValue(new MicrophoneError("denied"));
    const deps = container();
    renderWithContainer(deps, `/library/videos/${LIB}/watch?mode=shadowing`, WATCH, <WatchScreen />);
    fireEvent.click(await screen.findByRole("button", { name: "Record" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone access was blocked");
    const speaking = deps.speaking as unknown as { assessShadowing: ReturnType<typeof vi.fn> };
    expect(speaking.assessShadowing).not.toHaveBeenCalled();
  });

  it("starts one capture per click and releases a microphone granted after unmount", async () => {
    const rec = fakeRecorder();
    let grant!: (value: ReturnType<typeof fakeRecorder>) => void;
    recorder.startPcmRecorder.mockReturnValue(new Promise((resolve) => { grant = resolve; }));
    const view = renderWithContainer(container(), `/library/videos/${LIB}/watch?mode=shadowing`, WATCH, <WatchScreen />);
    const record = await screen.findByRole("button", { name: "Record" });
    fireEvent.click(record);
    fireEvent.click(record);
    expect(recorder.startPcmRecorder).toHaveBeenCalledTimes(1);

    view.unmount();
    await act(async () => { grant(rec); });
    expect(rec.dispose).toHaveBeenCalled();
  });

  it("maps no-speech errors to actionable copy", async () => {
    recorder.startPcmRecorder.mockResolvedValue(fakeRecorder());
    const deps = container(vi.fn().mockRejectedValue(new ApiError("validation", 422, { code: "no_speech_detected" })));
    renderWithContainer(deps, `/library/videos/${LIB}/watch?mode=shadowing`, WATCH, <WatchScreen />);
    fireEvent.click(await screen.findByRole("button", { name: "Record" }));
    fireEvent.click(await screen.findByRole("button", { name: /Stop/ }));
    expect(await screen.findByText(/could not hear any speech/)).toBeInTheDocument();
  });
});
