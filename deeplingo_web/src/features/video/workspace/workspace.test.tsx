import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../../app/container";
import { ApiError } from "../../../lib/api/errors";
import { YOUTUBE_EMBED_ORIGIN } from "../../../lib/media";
import type { TranscriptSegmentView } from "../../../lib/api/dto";
import { WatchScreen } from "../WatchScreen";
import { AppShell } from "../../../app/AppShell";
vi.mock("../../../app/AuthProvider", () => ({ useAuth: () => ({ signOut: vi.fn() }) }));
// These cases exercise the retained turn-based transport after Live is unavailable.
vi.mock("../../companion/RealtimeScreen", () => ({ RealtimeScreen: () => <p>Live unavailable</p> }));
beforeEach(() => vi.stubGlobal("scrollTo", vi.fn()));
afterEach(() => vi.unstubAllGlobals());
import { parseCompanionTurn } from "../../companion/companionModels";
import {
  formatClock,
  parseVideoWorkspace,
  regionSegments,
  type RegionPreparationView,
  type VideoWorkspaceView,
} from "./workspaceModels";
import { parseRegionResult, resultLines } from "./regionResult";
import { parseVideoParts, partAfter, partAt } from "./videoParts";

const LIB = "aaaaaaaa-2222-3333-4444-555555555555";
const TRACK = "bbbbbbbb-2222-3333-4444-555555555555";
const WATCH = "/library/videos/:libraryItemId/watch";

// Longer than the 20-segment preparation head: 30 sentences of 4 s each.
const segments: TranscriptSegmentView[] = Array.from({ length: 30 }, (_, i) => ({
  segment_id: `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`,
  sequence: i + 1,
  text: `Sentence number ${i + 1}.`,
  start_ms: i * 4000,
  end_ms: (i + 1) * 4000,
  translation: null,
  romanizations: [],
  learning_objects: [],
}));

// A tiny stand-in for the server: what was saved is what the next page load reads.
function fakeServer(initial: Partial<VideoWorkspaceView> = {}, preparation: RegionPreparationView | null = null) {
  let state: VideoWorkspaceView = { library_item_id: LIB, position_ms: null, region: null, ...initial };
  const playback = {
    getPlayableVideo: vi.fn().mockResolvedValue({
      library_item_id: LIB, video_id: LIB, provider: "youtube", external_video_id: "jNQXAC9IVRw",
      title: "Long talk", language_code: "en", duration_ms: 120_000,
    }),
    getTranscript: vi.fn().mockResolvedValue({
      library_item_id: LIB, language_code: "en", translation_language_code: null, segments,
    }),
    getWorkspace: vi.fn(async () => structuredClone(state)),
    saveWatchPosition: vi.fn(async (_id: string, ms: number) => {
      state = { ...state, position_ms: ms };
      return structuredClone(state);
    }),
    recordDictation: vi.fn(async () => undefined),
    recordLookup: vi.fn(async () => undefined),
    getRegionQuestions: vi.fn(async () => ({ status: "no_region", questions: [] })),
    // What the learner did in the part saved last, as the server sums it from the learning log.
    getRegionResult: vi.fn(async (_id: string, regionId: string) => parseRegionResult({
      region_id: regionId, dictation_attempts: 3, dictation_sentences: 2, dictation_accuracy: 78.4,
      shadowing_attempts: 0, shadowing_sentences: 0, shadowing_average: null, questions_answered: 2,
      questions_correct: 1, lookups: 1, words_saved: 1, practised: true,
    }, regionId)),
    saveStudyRegion: vi.fn(async (_id: string, start: string, end: string) => {
      const first = segments.findIndex((s) => s.segment_id === start);
      const last = segments.findIndex((s) => s.segment_id === end);
      state = {
        ...state,
        region: {
          transcript_id: TRACK, start_segment_id: start, end_segment_id: end,
          start_ms: segments[first].start_ms, end_ms: segments[last].end_ms, segment_count: last - first + 1,
          preparation: structuredClone(preparation),
        },
      };
      return structuredClone(state);
    }),
  };
  return {
    playback,
    get state() { return state; },
    // The server finished (or changed) the region's preparation since the last read.
    setPreparation(next: RegionPreparationView | null) {
      if (state.region) state = { ...state, region: { ...state.region, preparation: next } };
    },
  };
}

function studyPart(from: number, to: number, title: string) {
  return { start_segment_id: segments[from].segment_id, end_segment_id: segments[to].segment_id,
    start_ms: segments[from].start_ms, end_ms: segments[to].end_ms, segment_count: to - from + 1, title };
}
const STUDY_PARTS = { transcript_id: TRACK, source: "ai",
  parts: [studyPart(0, 9, "Mở đầu"), studyPart(10, 24, "Ở giữa"), studyPart(25, 28, "Gần cuối")] };
// The parts strip names each part "Part N: title (time)"; N follows STUDY_PARTS.
const partButton = (n: number) => within(screen.getByRole("group", { name: "Change part" })).getByRole("button", { name: new RegExp(`^Part ${n}:`) });

function renderWorkspace(playback: object, path = `/library/videos/${LIB}/watch`, companion: object = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={{ playback, companion: { getAgentConsent: vi.fn().mockResolvedValue({ status: "granted", decided_at: "2026-10-29T10:00:00Z" }), ...companion } } as unknown as AppContainer}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route element={<AppShell />}><Route path={WATCH} element={<WatchScreen />} /></Route>
          </Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

// Drives the embed the way YouTube does: trusted origin, from the player frame itself.
async function connectPlayer() {
  const frame = (await screen.findByTitle("Long talk")) as HTMLIFrameElement;
  const target = frame.contentWindow!;
  const posted = vi.spyOn(target, "postMessage").mockImplementation(() => {});
  const send = (data: object) =>
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { origin: YOUTUBE_EMBED_ORIGIN, source: target, data: JSON.stringify(data) }));
    });
  const commands = () =>
    posted.mock.calls.map(([raw]) => JSON.parse(raw as string) as { func: string; args: unknown[] });
  const seeks = () => commands().filter((c) => c.func === "seekTo").map((c) => c.args[0]);
  return { send, commands, seeks };
}

// A background refetch, as when the learner returns to the tab.
async function refocusWindow() {
  await act(async () => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  focusManager.setFocused(undefined);
}

describe("video workspace (M1 S1)", () => {
  it("resumes the saved position, saves while watching and resumes again after a reload", async () => {
    const server = fakeServer({ position_ms: 52_400 });
    const view = renderWorkspace(server.playback);
    const player = await connectPlayer();
    await screen.findByText("Continuing from 00:52");
    player.send({ event: "onReady" });
    expect(player.seeks()).toEqual([52.4]);

    player.send({ event: "infoDelivery", info: { currentTime: 60, playerState: 1 } });
    player.send({ event: "onStateChange", info: 2 });
    await waitFor(() => expect(server.playback.saveWatchPosition).toHaveBeenCalledWith(LIB, 60_000, { keepalive: false }));

    // Reload: a new page reads what the server kept.
    view.unmount();
    renderWorkspace(server.playback);
    const reloaded = await connectPlayer();
    await screen.findByText("Continuing from 01:00");
    reloaded.send({ event: "onReady" });
    expect(reloaded.seeks()).toEqual([60]);
  });

  it("switching tabs keeps one player and closing a tool returns it to the watched position", async () => {
    const server = fakeServer({ position_ms: 30_000 });
    renderWorkspace(server.playback);
    const player = await connectPlayer();
    await screen.findByText("Continuing from 00:30");
    player.send({ event: "onReady" });

    fireEvent.click(screen.getByRole("tab", { name: "Dictation" }));
    expect(screen.getByRole("tab", { name: "Dictation", selected: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    // The tool plays a sentence elsewhere in the video.
    player.send({ event: "infoDelivery", info: { currentTime: 4.2, playerState: 1 } });
    fireEvent.click(screen.getByRole("tab", { name: "Shadowing" }));
    fireEvent.click(screen.getByRole("tab", { name: "Questions" }));
    fireEvent.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(screen.getAllByTitle("Long talk")).toHaveLength(1);

    fireEvent.click(screen.getByRole("tab", { name: "Dictation" }));
    player.send({ event: "infoDelivery", info: { currentTime: 9, playerState: 1 } });
    fireEvent.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(screen.queryByRole("tab", { name: "Companion" })).not.toBeInTheDocument();
    expect(player.seeks().at(-1)).toBe(30);
    // While a tool held the player, the resume point stayed where the learner was watching.
    player.send({ event: "onStateChange", info: 2 });
    for (const [, ms] of server.playback.saveWatchPosition.mock.calls) expect(ms).toBe(30_000);
  });

  it("moves to another AI part by segment IDs and keeps it after reload", async () => {
    const server = fakeServer();
    const playback = { ...server.playback, getParts: vi.fn(async () => parseVideoParts(STUDY_PARTS)) };
    const view = renderWorkspace(playback);
    await screen.findByRole("group", { name: "Change part" });
    fireEvent.click(partButton(3));

    await screen.findByText(/01:40–01:56/);
    expect(server.playback.saveStudyRegion).toHaveBeenCalledWith(LIB, segments[25].segment_id, segments[28].segment_id);
    const transcript = screen.getByRole("region", { name: "Transcript" });
    expect(transcript.querySelectorAll("[data-in-region]")).toHaveLength(4);
    expect(screen.getByText(/4 sentences/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose part" })).toBeNull();

    // Tools practise only the chosen part.
    fireEvent.click(screen.getByRole("tab", { name: "Dictation" }));
    expect(screen.getByRole("tab", { name: "Dictation" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Transcript", { selector: ".transcript-scroll" })).not.toBeVisible();

    view.unmount();
    renderWorkspace(playback);
    await screen.findByText(/01:40–01:56/);
    expect(screen.getByRole("region", { name: "Transcript" }).querySelectorAll("[data-in-region]")).toHaveLength(4);
  });

  it("opens the part named in the link an agent card built, saves it and plays from its first sentence", async () => {
    const server = fakeServer();
    const playback = { ...server.playback, getParts: vi.fn(async () => parseVideoParts(STUDY_PARTS)) };
    renderWorkspace(playback, `/library/videos/${LIB}/watch?region=${segments[25].segment_id}_${segments[28].segment_id}`);
    await screen.findByText(/01:40–01:56/);
    // The requested part replaces the automatic one: it was saved once and the first AI part was never opened.
    expect(server.playback.saveStudyRegion).toHaveBeenCalledTimes(1);
    expect(server.playback.saveStudyRegion).toHaveBeenCalledWith(LIB, segments[25].segment_id, segments[28].segment_id);
    expect(screen.getByRole("region", { name: "Transcript" }).querySelectorAll("[data-in-region]")).toHaveLength(4);
  });

  it("ignores a malformed region in the link and opens the automatic part", async () => {
    const server = fakeServer();
    const playback = { ...server.playback, getParts: vi.fn(async () => parseVideoParts(STUDY_PARTS)) };
    renderWorkspace(playback, `/library/videos/${LIB}/watch?region=not-a-region`);
    await screen.findByRole("group", { name: "Change part" });
    await waitFor(() => expect(server.playback.saveStudyRegion).toHaveBeenCalledWith(LIB, segments[0].segment_id, segments[9].segment_id));
  });

  it("shows a server refusal of a part", async () => {
    const server = fakeServer();
    server.playback.saveStudyRegion.mockRejectedValueOnce(new ApiError("validation", 422, { code: "region_invalid" }));
    renderWorkspace({ ...server.playback, getParts: vi.fn(async () => parseVideoParts(STUDY_PARTS)) });
    expect(await screen.findByRole("alert")).toHaveTextContent("too long");
  });

  it("a failed workspace read still plays the video and never overwrites the saved position", async () => {
    const server = fakeServer({ position_ms: 600_000 });
    server.playback.getWorkspace.mockRejectedValue(new ApiError("server", 503, {}));
    const view = renderWorkspace(server.playback);
    const player = await connectPlayer();
    await screen.findByRole("region", { name: "Transcript" });
    await waitFor(() => expect(server.playback.getWorkspace).toHaveBeenCalled());
    player.send({ event: "onReady" });
    player.send({ event: "infoDelivery", info: { currentTime: 5, playerState: 1 } });
    player.send({ event: "onStateChange", info: 2 });
    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });
    view.unmount();
    expect(player.seeks()).toEqual([]);
    expect(server.playback.saveWatchPosition).not.toHaveBeenCalled();
    expect(server.state.position_ms).toBe(600_000);
  });

  it("after a failed read, a successful retry offers the saved point to a learner already watching", async () => {
    const server = fakeServer({ position_ms: 600_000 });
    server.playback.getWorkspace.mockRejectedValueOnce(new ApiError("server", 503, {}));
    renderWorkspace(server.playback);
    const player = await connectPlayer();
    await waitFor(() => expect(server.playback.getWorkspace).toHaveBeenCalledTimes(1));
    player.send({ event: "onReady" });
    player.send({ event: "infoDelivery", info: { currentTime: 5, playerState: 1 } });
    player.send({ event: "onStateChange", info: 2 });

    await refocusWindow();
    expect(await screen.findByText("You were at 10:00")).toBeInTheDocument();
    expect(player.seeks()).toEqual([]);
    expect(server.playback.saveWatchPosition).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Continue 10:00" }));
    expect(player.seeks()).toEqual([600]);
    player.send({ event: "infoDelivery", info: { currentTime: 607, playerState: 1 } });
    player.send({ event: "onStateChange", info: 2 });
    await waitFor(() => expect(server.playback.saveWatchPosition).toHaveBeenCalledWith(LIB, 607_000, { keepalive: false }));
    for (const [, ms] of server.playback.saveWatchPosition.mock.calls) expect(ms).not.toBe(5000);
  });

  it("after a failed read, a successful retry resumes a learner who has not started", async () => {
    const server = fakeServer({ position_ms: 600_000 });
    server.playback.getWorkspace.mockRejectedValueOnce(new ApiError("server", 503, {}));
    renderWorkspace(server.playback);
    const player = await connectPlayer();
    await waitFor(() => expect(server.playback.getWorkspace).toHaveBeenCalledTimes(1));
    player.send({ event: "onReady" });
    await refocusWindow();
    expect(await screen.findByText("Continuing from 10:00")).toBeInTheDocument();
    expect(player.seeks()).toEqual([600]);
    expect(screen.queryByText("You were at 10:00")).not.toBeInTheDocument();
  });

  it("a successful read with no saved position saves while watching", async () => {
    const server = fakeServer();
    renderWorkspace(server.playback);
    const player = await connectPlayer();
    await waitFor(() => expect(server.playback.getWorkspace).toHaveBeenCalled());
    await screen.findByRole("region", { name: "Transcript" });
    player.send({ event: "onReady" });
    player.send({ event: "infoDelivery", info: { currentTime: 5, playerState: 1 } });
    player.send({ event: "onStateChange", info: 2 });
    await waitFor(() => expect(server.playback.saveWatchPosition).toHaveBeenCalledWith(LIB, 5000, { keepalive: false }));
    expect(player.seeks()).toEqual([]);
  });

  it("opening a tool from a deep link returns to the resume point when closed", async () => {
    const server = fakeServer({ position_ms: 12_000 });
    renderWorkspace(server.playback, `/library/videos/${LIB}/watch?mode=shadowing`);
    const player = await connectPlayer();
    expect(await screen.findByRole("tab", { name: "Shadowing", selected: true })).toBeInTheDocument();
    await screen.findByText("Continuing from 00:12");
    player.send({ event: "onReady" });
    player.send({ event: "infoDelivery", info: { currentTime: 80, playerState: 1 } });
    fireEvent.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(player.seeks().at(-1)).toBe(12);
  });
});

// Mirrors backend CompanionTurnView with an M1 S3 practice suggestion on sentence 12.
function companionOpening() {
  return parseCompanionTurn({
    session_ticket: "signed.ticket", expires_at: "2026-10-19T10:00:00Z", turn: 0, max_turns: 30, finished: false,
    language_code: "en", support_language_code: "vi", entry: "video", library_item_id: LIB, topic: "Long talk",
    learner_transcript: null, reply: "What happens in this part?", reply_support: "Chuyện gì xảy ra ở đoạn này?",
    hints: { question: null, items: [], frame: null, model_sentence: null }, correction: null, used_items: [],
    next: "continue", audio: null, audio_status: "unavailable",
    practice_suggestion: {
      tool: "dictation", segment_id: segments[11].segment_id, start_ms: 44_000, end_ms: 48_000,
      reason: "Nghe chép câu này để nhận ra từng từ.",
    },
  });
}

describe("practice log (M1 S4)", () => {
  it("a checked Dictation answer is reported once with a fresh ID, and a failed report changes nothing", async () => {
    const server = fakeServer();
    server.playback.recordDictation.mockRejectedValueOnce(new ApiError("server", 503, {}));
    renderWorkspace(server.playback);
    await connectPlayer();
    fireEvent.click(await screen.findByRole("tab", { name: "Dictation" }));
    fireEvent.click(screen.getByRole("button", { name: "Hard · type it" }));
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    fireEvent.change(screen.getByLabelText("Type what you hear"), { target: { value: "Sentence number one" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(server.playback.recordDictation).toHaveBeenCalledTimes(1));
    const [item, event] = server.playback.recordDictation.mock.calls[0] as unknown as [string, Record<string, unknown>];
    expect(item).toBe(LIB);
    expect(event).toEqual({
      id: expect.stringMatching(/^[0-9a-f-]{36}$/), segment_id: segments[0].segment_id, level: "hard",
      answer: "Sentence number one", hint_shown: false,
    });
    expect(screen.getByText(/of 3 words right/)).toBeInTheDocument();
  });
});

describe("companion in the workspace (M1 S3)", () => {
  it("starts only when asked and its suggestion opens Dictation at that sentence", async () => {
    const server = fakeServer();
    const companion = { start: vi.fn().mockResolvedValue(companionOpening()), turn: vi.fn(),
                        finish: vi.fn().mockResolvedValue({}), setMemoryEnabled: vi.fn() };
    renderWorkspace(server.playback, undefined, companion);
    fireEvent.click(screen.getByRole("button", { name: "Open agent" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use recorded turns" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Start talking" })).toBeEnabled());
    fireEvent.click(await screen.findByRole("button", { name: "Start talking" }));
    await screen.findByText("What happens in this part?");
    expect(companion.start).toHaveBeenCalledWith("video", LIB, { segment_id: segments[0].segment_id });

    // A suggestion is only a button: nothing opens until the learner chooses it.
    expect(screen.getByRole("dialog", { name: "Agent conversation" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open Dictation" }));
    expect(screen.getByRole("tab", { name: "Dictation", selected: true })).toBeInTheDocument();
    expect(screen.getByText("Starting from sentence 12 of 30.")).toBeInTheDocument();

    // Closing the tool returns to the same conversation; it was not restarted.
    fireEvent.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(screen.getByText("What happens in this part?")).toBeVisible();
    expect(companion.start).toHaveBeenCalledTimes(1);
    // Opening Dictation by hand afterwards starts at the watched sentence again.
    fireEvent.click(screen.getByRole("tab", { name: "Dictation" }));
    expect(screen.getByText("Starting from sentence 1 of 30.")).toBeInTheDocument();
  });

  it("opening the video does not start a conversation", async () => {
    const server = fakeServer();
    const companion = { start: vi.fn(), turn: vi.fn(), finish: vi.fn(), setMemoryEnabled: vi.fn() };
    renderWorkspace(server.playback, undefined, companion);
    expect(screen.queryByRole("button", { name: "Start talking" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open agent" }));
    await screen.findByRole("button", { name: "Use recorded turns" });
    expect(companion.start).not.toHaveBeenCalled();
  });
});

const PENDING: RegionPreparationView = { status: "pending", usable_count: 0, retryable: false, reset_at: null, questions_status: null };

async function seedPart(server: ReturnType<typeof fakeServer>) {
  await server.playback.saveStudyRegion(LIB, segments[2].segment_id, segments[4].segment_id);
}

describe("study part preparation (M1 S2)", () => {
  it("shows the part being prepared and reads it again until it is ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const server = fakeServer({}, PENDING);
      await seedPart(server);
      renderWorkspace(server.playback);
      await screen.findByText(/Preparing words for this part/);
      const reads = server.playback.getWorkspace.mock.calls.length;
      server.setPreparation({ status: "ready", usable_count: 3, retryable: false, reset_at: null, questions_status: null });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      await screen.findByText(/Words ready/);
      expect(server.playback.getWorkspace.mock.calls.length).toBeGreaterThan(reads);
      // Ready is final: no more polling.
      const settled = server.playback.getWorkspace.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });
      expect(server.playback.getWorkspace.mock.calls.length).toBe(settled);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed, retryable preparation asks again for the same part", async () => {
    const server = fakeServer({}, { status: "failed", usable_count: 0, retryable: true, reset_at: null, questions_status: null });
    await seedPart(server);
    renderWorkspace(server.playback);
    await screen.findByText(/We could not prepare words for this part/);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(server.playback.saveStudyRegion).toHaveBeenCalledTimes(2));
    expect(server.playback.saveStudyRegion).toHaveBeenLastCalledWith(LIB, segments[2].segment_id, segments[4].segment_id);
  });

  it("a part that is not prepared still keeps every practice tool available", async () => {
    const server = fakeServer({}, { status: "budget_exhausted", usable_count: 0, retryable: false, reset_at: null, questions_status: null });
    await seedPart(server);
    renderWorkspace(server.playback);
    await screen.findByText(/You have prepared many parts today/);
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Dictation" }));
    expect(screen.getByRole("button", { name: "Start dictation" })).toBeEnabled();
  });
});

describe("workspace decoder", () => {
  const region = {
    transcript_id: TRACK, start_segment_id: segments[0].segment_id, end_segment_id: segments[1].segment_id,
    start_ms: 0, end_ms: 8000, segment_count: 2, preparation: null,
  };

  it("accepts the server view and rejects another item, bad numbers and bad regions", () => {
    expect(parseVideoWorkspace({ library_item_id: LIB, position_ms: 5, region, updated_at: null }, LIB).region).toEqual(region);
    expect(parseVideoWorkspace({ library_item_id: LIB, position_ms: null, region: null }, LIB).position_ms).toBeNull();
    const preparing = { ...region, preparation: { ...PENDING, reset_at: "2026-10-20T01:00:00Z" } };
    expect(parseVideoWorkspace({ library_item_id: LIB, position_ms: 1, region: preparing }, LIB).region?.preparation)
      .toEqual(preparing.preparation);
    for (const bad of [
      { library_item_id: TRACK, position_ms: 1, region: null },
      { library_item_id: LIB, position_ms: -1, region: null },
      { library_item_id: LIB, position_ms: "5", region: null },
      { library_item_id: LIB, position_ms: 1, region: { ...region, end_ms: 0 } },
      { library_item_id: LIB, position_ms: 1, region: { ...region, start_segment_id: "x" } },
      { library_item_id: LIB, position_ms: 1, region: { ...region, segment_count: 0 } },
      { library_item_id: LIB, position_ms: 1, region: { ...region, preparation: { ...PENDING, status: "mastered" } } },
      { library_item_id: LIB, position_ms: 1, region: { ...region, preparation: { ...PENDING, retryable: "no" } } },
      { library_item_id: LIB, position_ms: 1, region: { ...region, preparation: { ...PENDING, usable_count: -1 } } },
      { library_item_id: LIB, position_ms: 1, region: { ...region, preparation: { ...PENDING, reset_at: "soon" } } },
      null,
    ]) {
      expect(() => parseVideoWorkspace(bad, LIB)).toThrow(ApiError);
    }
  });

  it("maps a region onto the transcript only when this transcript holds it", () => {
    expect(regionSegments(segments, region)).toHaveLength(2);
    expect(regionSegments(segments, { ...region, start_segment_id: TRACK })).toEqual([]);
    expect(regionSegments(segments, null)).toEqual([]);
    expect(formatClock(520_000)).toBe("08:40");
    expect(formatClock(3_725_000)).toBe("1:02:05");
  });
});

describe("part result", () => {
  it("Finish shows the server result of this part and Next studies the following part", async () => {
    const server = fakeServer();
    await server.playback.saveStudyRegion(LIB, segments[0].segment_id, segments[9].segment_id);  // the first AI part
    renderWorkspace({ ...server.playback, getParts: vi.fn(async () => parseVideoParts(STUDY_PARTS)) });
    fireEvent.click(await screen.findByRole("button", { name: "Finish" }));
    await screen.findByRole("heading", { name: /^Result for / });
    const [item, regionId] = server.playback.getRegionResult.mock.calls[0] as unknown as [string, string];
    expect(item).toBe(LIB);
    expect(regionId).toBe(`${server.state.region?.start_segment_id}_${server.state.region?.end_segment_id}`);
    expect(await screen.findByText("78% of words right, 3 attempts")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 right")).toBeInTheDocument();
    expect(screen.getByText("New words saved")).toBeInTheDocument();
    expect(within(screen.getByRole("heading", { name: /^Result for / }).closest("section")!).queryByText("Shadowing")).toBeNull();
    expect(screen.getByRole("heading", { name: /^Result for / }).closest(".watch-right")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Next: / }));
    await waitFor(() => expect(server.playback.saveStudyRegion).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("heading", { name: /^Result for / })).toBeNull());
  });

  it("a failed result can be read again, and an untouched part says so", async () => {
    const server = fakeServer();
    server.playback.getRegionResult.mockRejectedValueOnce(new ApiError("server", 503, {}));
    await seedPart(server);
    renderWorkspace(server.playback);
    fireEvent.click(await screen.findByRole("button", { name: "Finish" }));
    await screen.findByText("We could not load the result. Please try again.");
    server.playback.getRegionResult.mockImplementationOnce(async (_id: string, regionId: string) => parseRegionResult({
      region_id: regionId, practised: false, dictation_attempts: 0, dictation_sentences: 0, dictation_accuracy: null,
      shadowing_attempts: 0, shadowing_sentences: 0, shadowing_average: null, questions_answered: 0,
      questions_correct: 0, lookups: 0, words_saved: 0,
    }, regionId));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("Nothing practised in this part yet.");
  });

  it("the decoder rejects another part's result and the lines skip what was not practised", () => {
    const id = "cccccccc-2222-3333-4444-555555555555_dddddddd-2222-3333-4444-555555555555";
    const empty = { region_id: id, practised: false, dictation_attempts: 0, dictation_sentences: 0, dictation_accuracy: null,
      shadowing_attempts: 0, shadowing_sentences: 0, shadowing_average: null, questions_answered: 0, questions_correct: 0,
      lookups: 0, words_saved: 0 };
    expect(() => parseRegionResult({ ...empty, region_id: LIB }, id)).toThrow(ApiError);
    expect(() => parseRegionResult({ ...empty, shadowing_average: 120 }, id)).toThrow(ApiError);
    expect(() => parseRegionResult({ ...empty, words_saved: -1 }, id)).toThrow(ApiError);
    expect(resultLines(parseRegionResult(empty, id), (text) => text)).toEqual([]);
    expect(resultLines(parseRegionResult({ ...empty, shadowing_attempts: 2, shadowing_average: 71.6, questions_answered: 3,
      questions_correct: 2 }, id), (text, params) => text.replace(/\{(\w+)\}/g, (m, name: string) => String(params?.[name] ?? m)))).toEqual([
      { label: "Shadowing", value: "Average score 72, 2 attempts" },
      { label: "Questions", value: "2 of 3 right" },
    ]);
  });
});

describe("pilot fixes (M1 S7b)", () => {
  it("a new study part ends the conversation about the old one and starts fresh", async () => {
    const server = fakeServer();
    const companion = { start: vi.fn().mockResolvedValue(companionOpening()), turn: vi.fn(),
                        finish: vi.fn().mockResolvedValue({}), setMemoryEnabled: vi.fn() };
    await seedPart(server);
    renderWorkspace({ ...server.playback, getParts: vi.fn(async () => parseVideoParts(STUDY_PARTS)) }, undefined, companion);
    await screen.findByRole("group", { name: "Change part" });  // saved: the companion is about this part
    fireEvent.click(screen.getByRole("button", { name: "Open agent" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use recorded turns" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Start talking" })).toBeEnabled());
    fireEvent.click(await screen.findByRole("button", { name: "Start talking" }));
    await screen.findByText("What happens in this part?");
    fireEvent.click(partButton(2));
    await waitFor(() => expect(screen.queryByText("What happens in this part?")).toBeNull());
    expect(await screen.findByRole("button", { name: "Use recorded turns" })).toBeInTheDocument();
    expect(companion.start).toHaveBeenCalledTimes(1);
  });

  it("a busy preparation keeps every tool and offers to ask again", async () => {
    const server = fakeServer({}, { status: "busy", usable_count: 0, retryable: true, reset_at: null, questions_status: null });
    await seedPart(server);
    renderWorkspace(server.playback);
    await screen.findByText(/Many parts are being prepared right now/);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(server.playback.saveStudyRegion).toHaveBeenCalledTimes(2));
  });

  it("questions for a part that was never prepared are not polled", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const server = fakeServer();
      server.playback.getRegionQuestions.mockResolvedValue({ status: "not_prepared", questions: [] });
      renderWorkspace(server.playback, `/library/videos/${LIB}/watch?mode=questions`);
      await screen.findByText(/Questions come once this part is prepared/);
      const reads = server.playback.getRegionQuestions.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });
      expect(server.playback.getRegionQuestions.mock.calls.length).toBe(reads);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Xem ngữ cảnh (M1 S7d)", () => {
  it("opens the video at the Quick review sentence instead of the saved position", async () => {
    const server = fakeServer({ position_ms: 52_400 });
    renderWorkspace(server.playback, `/library/videos/${LIB}/watch?at=8000`);
    const player = await connectPlayer();
    await screen.findByText("Continuing from 00:08");
    player.send({ event: "onReady" });
    expect(player.seeks()).toEqual([8]);
  });
});

// 2026-11-05: the study region opens on a part cut by AI on the server.
describe("AI study parts", () => {
  const part = (from: number, to: number, title: string) => ({
    start_segment_id: segments[from].segment_id, end_segment_id: segments[to].segment_id,
    start_ms: segments[from].start_ms, end_ms: segments[to].end_ms, segment_count: to - from + 1, title,
  });
  const aiParts = { transcript_id: TRACK, source: "ai", parts: [part(0, 9, "Chào hỏi"), part(10, 19, "Gọi món"), part(20, 29, "Thanh toán")] };

  it("opens the part holding the saved position, shows its title and never moves the video", async () => {
    const server = fakeServer({ position_ms: 50_000 });
    const playback = { ...server.playback, getParts: vi.fn(async () => parseVideoParts(aiParts)) };
    renderWorkspace(playback);
    await waitFor(() => expect(playback.saveStudyRegion).toHaveBeenCalledWith(LIB, segments[10].segment_id, segments[19].segment_id));
    expect(playback.saveStudyRegion).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Gọi món")).toBeInTheDocument();
  });

  it("keeps a region the learner already has", async () => {
    const server = fakeServer();
    await server.playback.saveStudyRegion(LIB, segments[2].segment_id, segments[4].segment_id);
    server.playback.saveStudyRegion.mockClear();
    const playback = { ...server.playback, getParts: vi.fn(async () => parseVideoParts(aiParts)) };
    renderWorkspace(playback);
    await waitFor(() => expect(playback.getParts).toHaveBeenCalled());
    await screen.findByRole("group", { name: "Change part" });
    expect(playback.saveStudyRegion).not.toHaveBeenCalled();
  });

  it("without parts the learner can ask for them again", async () => {
    const server = fakeServer();
    const playback = { ...server.playback, getParts: vi.fn(async () => { throw new ApiError("server", 503, {}); }) };
    renderWorkspace(playback);
    await waitFor(() => expect(playback.getParts).toHaveBeenCalled());
    expect(playback.saveStudyRegion).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(playback.getParts).toHaveBeenCalledTimes(2));
  });

  it("accepts the server parts and finds the part at a position and the part after a region", () => {
    const parsed = parseVideoParts(aiParts);
    expect(partAt(parsed.parts, 0)?.title).toBe("Chào hỏi");
    expect(partAt(parsed.parts, 999_999)?.title).toBe("Chào hỏi");
    expect(partAfter(parsed.parts, { end_segment_id: segments[9].segment_id })?.title).toBe("Gọi món");
    expect(partAfter(parsed.parts, { end_segment_id: segments[29].segment_id })).toBeNull();
    expect(() => parseVideoParts({ ...aiParts, parts: [] })).toThrow(ApiError);
    expect(() => parseVideoParts({ ...aiParts, source: "guess" })).toThrow(ApiError);
    expect(() => parseVideoParts({ ...aiParts, parts: [{ ...aiParts.parts[0], end_ms: 0 }] })).toThrow(ApiError);
  });
});
