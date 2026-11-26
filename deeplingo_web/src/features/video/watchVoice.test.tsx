import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { YOUTUBE_EMBED_ORIGIN } from "../../lib/media";
import type { TranscriptSegmentView } from "../../lib/api/dto";
import { WatchScreen } from "./WatchScreen";
import { AppShell } from "../../app/AppShell";
vi.mock("../../app/AuthProvider", () => ({ useAuth: () => ({ signOut: vi.fn() }) }));

const LIB = "aaaaaaaa-2222-3333-4444-555555555555";

const recorder = { takeChunk: vi.fn(() => new Int16Array(1600)), stop: vi.fn(), dispose: vi.fn() };
const player = { enqueue: vi.fn(), flush: vi.fn(), close: vi.fn() };
const startPcmRecorder = vi.hoisted(() => vi.fn());

vi.mock("../../lib/audio/pcmRecorder", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/audio/pcmRecorder")>()),
  startPcmRecorder,
}));
vi.mock("../../lib/audio/pcmPlayer", () => ({ createPcmPlayer: () => player }));

class FakeSocket {
  static last: FakeSocket | null = null;
  readyState = 0;
  binaryType = "blob";
  sent: (string | ArrayBuffer)[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  static OPEN = 1;
  constructor(readonly url: string) { FakeSocket.last = this; }
  send(data: string | ArrayBuffer) { this.sent.push(data); }
  close(code = 1000) { this.readyState = 3; this.onclose?.({ code }); }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
  json(): Record<string, unknown>[] {
    return this.sent.filter((item): item is string => typeof item === "string").map((item) => JSON.parse(item));
  }
}

const segments: TranscriptSegmentView[] = Array.from({ length: 6 }, (_, i) => ({
  segment_id: `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`,
  sequence: i + 1, text: `Sentence number ${i + 1}.`, start_ms: i * 4000, end_ms: (i + 1) * 4000,
  translation: null, romanizations: [], learning_objects: [],
}));

function mount() {
  const playback = {
    getPlayableVideo: vi.fn().mockResolvedValue({
      library_item_id: LIB, video_id: LIB, provider: "youtube", external_video_id: "jNQXAC9IVRw",
      title: "Long talk", language_code: "en", duration_ms: 120_000,
    }),
    getTranscript: vi.fn().mockResolvedValue({
      library_item_id: LIB, language_code: "en", translation_language_code: null, segments,
    }),
    getWorkspace: vi.fn(async () => ({ library_item_id: LIB, position_ms: null, region: null })),
    saveWatchPosition: vi.fn(async () => ({ library_item_id: LIB, position_ms: null, region: null })),
  };
  const companion = { start: vi.fn().mockResolvedValue(null), getAgentConsent: vi.fn().mockResolvedValue({ status: "granted", decided_at: "2026-10-29T10:00:00Z" }) };
  const gateway = { currentSession: vi.fn().mockResolvedValue({ userId: "u1", accessToken: "a.b.c" }) };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={{ playback, companion, gateway, config: { apiBaseUrl: "https://api.example.com" } } as unknown as AppContainer}>
        <MemoryRouter initialEntries={[`/library/videos/${LIB}/watch`]}>
          <Routes><Route element={<AppShell />}><Route path="/library/videos/:libraryItemId/watch" element={<WatchScreen />} /></Route></Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

async function connectPlayer() {
  const frame = (await screen.findByTitle("Long talk")) as HTMLIFrameElement;
  await userEvent.click(screen.getByRole("button", { name: "Open agent" }));
  const target = frame.contentWindow!;
  const posted = vi.spyOn(target, "postMessage").mockImplementation(() => {});
  const send = (data: object) => act(() => {
    window.dispatchEvent(new MessageEvent("message", { origin: YOUTUBE_EMBED_ORIGIN, source: target, data: JSON.stringify(data) }));
  });
  const commands = () => posted.mock.calls.map(([raw]) => JSON.parse(raw as string) as { func: string; args: unknown[] });
  return { send, commands };
}

beforeEach(() => {
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal("WebSocket", FakeSocket);
  FakeSocket.last = null;
  startPcmRecorder.mockReset();
  startPcmRecorder.mockResolvedValue(recorder);
});

afterEach(() => vi.unstubAllGlobals());

describe("agent on the watch screen", () => {
  it("releases live audio when the shared Tata panel is closed", async () => {
    mount();
    await connectPlayer();
    recorder.dispose.mockClear();
    player.close.mockClear();
    await userEvent.click(await screen.findByRole("button", { name: "Start talking" }));
    await vi.waitFor(() => expect(FakeSocket.last).not.toBeNull());
    act(() => {
      FakeSocket.last!.open();
      FakeSocket.last!.receive({ type: "ready", max_seconds: 600, language_code: "en", topic: "Long talk" });
    });
    await userEvent.click(screen.getByRole("button", { name: "Close agent" }));
    expect(screen.queryByRole("dialog", { name: "Agent conversation" })).not.toBeInTheDocument();
    expect(recorder.dispose).toHaveBeenCalledTimes(1);
    expect(player.close).toHaveBeenCalled();
    expect(FakeSocket.last!.readyState).toBe(3);
  });

  it("does not open the microphone or a connection until the learner asks to talk", async () => {
    mount();
    await connectPlayer();
    await screen.findByRole("button", { name: "Start talking" });
    expect(startPcmRecorder).not.toHaveBeenCalled();
    expect(FakeSocket.last).toBeNull();
    expect(screen.queryByRole("button", { name: "Resume video" })).not.toBeInTheDocument();
  });

  it("pauses the video and tells the server which part is playing", async () => {
    mount();
    const frame = await connectPlayer();
    frame.send({ event: "onReady" });
    frame.send({ event: "infoDelivery", info: { currentTime: 9, playerState: 1 } });  // inside sentence 3
    await userEvent.click(await screen.findByRole("button", { name: "Start talking" }));
    expect(frame.commands().map((command) => command.func)).toContain("pauseVideo");
    await screen.findByRole("button", { name: "Connecting…" });
    await vi.waitFor(() => expect(FakeSocket.last).not.toBeNull());
    act(() => FakeSocket.last!.open());
    const start = FakeSocket.last!.json().find((message) => message.type === "start")!;
    expect(start).toMatchObject({ entry: "video", library_item_id: LIB, segment_id: segments[2].segment_id });
  });

  it("waits for the learner after the agent: the video stays paused until Resume video", async () => {
    mount();
    const frame = await connectPlayer();
    frame.send({ event: "onReady" });
    frame.send({ event: "infoDelivery", info: { currentTime: 5, playerState: 1 } });
    await userEvent.click(await screen.findByRole("button", { name: "Start talking" }));
    await vi.waitFor(() => expect(FakeSocket.last).not.toBeNull());
    act(() => {
      FakeSocket.last!.open();
      FakeSocket.last!.receive({ type: "ready", max_seconds: 600, language_code: "en", topic: "Long talk" });
      FakeSocket.last!.receive({ type: "ended", reason: "learner_ended", follow_ups: [] });
      FakeSocket.last!.close(1000);
    });
    frame.send({ event: "infoDelivery", info: { currentTime: 5, playerState: 2 } });  // paused
    expect(frame.commands().map((command) => command.func)).not.toContain("playVideo");
    await userEvent.click(await screen.findByRole("button", { name: "Resume video" }));
    expect(frame.commands().map((command) => command.func)).toContain("playVideo");
    frame.send({ event: "infoDelivery", info: { currentTime: 5.5, playerState: 1 } });
    expect(screen.queryByRole("button", { name: "Resume video" })).not.toBeInTheDocument();
  });

  it("pauses the video again when the learner starts speaking, even if it was started again", async () => {
    mount();
    const frame = await connectPlayer();
    frame.send({ event: "onReady" });
    frame.send({ event: "infoDelivery", info: { currentTime: 5, playerState: 1 } });
    await userEvent.click(await screen.findByRole("button", { name: "Start talking" }));
    await vi.waitFor(() => expect(FakeSocket.last).not.toBeNull());
    act(() => {
      FakeSocket.last!.open();
      FakeSocket.last!.receive({ type: "ready", max_seconds: 600, language_code: "en", topic: "Long talk" });
    });
    const pauses = () => frame.commands().filter((command) => command.func === "pauseVideo").length;
    const before = pauses();
    frame.send({ event: "infoDelivery", info: { currentTime: 6, playerState: 1 } });  // the learner played it again
    act(() => FakeSocket.last!.receive({ type: "transcript", role: "learner", text: "I think" }));
    expect(pauses()).toBe(before + 1);
  });
});
