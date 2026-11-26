import { StrictMode } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate, useSearchParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import type { PcmRecorder } from "../../lib/audio/pcmRecorder";
import { RealtimeScreen } from "./RealtimeScreen";

const audio = vi.hoisted(() => ({ start: vi.fn(), player: vi.fn() }));
vi.mock("../../lib/audio/pcmRecorder", async (original) => ({
  ...(await original<typeof import("../../lib/audio/pcmRecorder")>()), startPcmRecorder: audio.start,
}));
vi.mock("../../lib/audio/pcmPlayer", () => ({ createPcmPlayer: audio.player }));

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 0;
  binaryType = "blob";
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = 3; });
  constructor() { Socket.instances.push(this); }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(value: unknown) { this.onmessage?.({ data: value instanceof ArrayBuffer ? value : JSON.stringify(value) }); }
  closed() { this.onclose?.({ code: 1000 }); }
}

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function recorder(): PcmRecorder {
  return { takeChunk: vi.fn(() => new Int16Array(1600)), stop: vi.fn(), dispose: vi.fn() };
}
function player() { return { enqueue: vi.fn(), flush: vi.fn(), close: vi.fn() }; }
const ITEM = "11111111-1111-4111-8111-111111111111";
const CONCEPT = "22222222-2222-4222-8222-222222222222";
const AUTH = { userId: "synthetic-user", accessToken: "dummy.test.token" };
const clients: QueryClient[] = [];
function Move() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/agent?mode=voice&entry=video&scope=video&item=" + CONCEPT)}>Another video</button>;
}
// The agent screen starts a new conversation whenever the link changes.
function Keyed() {
  const [params] = useSearchParams();
  return <RealtimeScreen key={params.toString()} />;
}
function mount(currentSession = vi.fn(async () => AUTH)) {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(query);
  const container = { config: { apiBaseUrl: "/api/v1/v3" }, gateway: { currentSession },
    onboarding: { loadProfile: async () => ({ learning_language: "en", support_language: "vi" }) },
    companion: { getAgentConsent: async () => ({ status: "granted", decided_at: "2026-10-29T10:00:00Z" }) },
    lists: { list: async () => [] },
  } as unknown as AppContainer;
  return render(<StrictMode><MemoryRouter initialEntries={[`/agent?mode=voice&entry=video&scope=video&item=${ITEM}`]}>
    <QueryClientProvider client={query}><ContainerProvider container={container}><Move /><Routes>
      <Route path="/agent" element={<Keyed />} />
    </Routes></ContainerProvider></QueryClientProvider>
  </MemoryRouter></StrictMode>);
}
beforeEach(() => { vi.stubGlobal("WebSocket", Socket); Socket.instances = []; audio.start.mockReset(); audio.player.mockReset(); audio.player.mockImplementation(player); });
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals(); });

describe("speaking startup cancellation", () => {
  it("does not ask for the microphone or connect when authentication resolves after leaving", async () => {
    const pending = deferred<typeof AUTH>();
    const view = mount(vi.fn(() => pending.promise));
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    view.unmount();
    await act(async () => { pending.resolve(AUTH); });
    expect(audio.start).not.toHaveBeenCalled();
    expect(audio.player).not.toHaveBeenCalled();
    expect(Socket.instances).toHaveLength(0);
  });

  it("disposes a late microphone grant after leaving without opening a socket", async () => {
    const pending = deferred<PcmRecorder>(), capture = recorder(), playback = player();
    audio.start.mockReturnValue(pending.promise); audio.player.mockReturnValue(playback);
    const view = mount();
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    expect(audio.start).toHaveBeenCalledTimes(1);
    view.unmount();
    await act(async () => { pending.resolve(capture); });
    expect(capture.dispose).toHaveBeenCalledTimes(1);
    expect(playback.close).toHaveBeenCalledTimes(1);
    expect(Socket.instances).toHaveLength(0);
  });

  it("cancels a pending capture when the learner moves to another video", async () => {
    const pending = deferred<PcmRecorder>(), capture = recorder();
    audio.start.mockReturnValue(pending.promise);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    await userEvent.click(screen.getByRole("button", { name: "Another video" }));
    await act(async () => { pending.resolve(capture); });
    expect(capture.dispose).toHaveBeenCalledTimes(1);
    expect(Socket.instances).toHaveLength(0);
    expect(await screen.findByRole("button", { name: "Start" })).toBeEnabled();
  });

  it("ignores a pending capture rejection after leaving", async () => {
    const pending = deferred<PcmRecorder>(), playback = player();
    audio.start.mockReturnValue(pending.promise); audio.player.mockReturnValue(playback);
    const view = mount();
    await userEvent.click(await screen.findByRole("button", { name: "Start" })); view.unmount();
    await act(async () => { pending.reject(new Error("synthetic capture failure")); });
    expect(playback.close).toHaveBeenCalledTimes(1);
    expect(Socket.instances).toHaveLength(0);
  });

  it("keeps a restarted conversation alive when the previous socket closes or sends late data", async () => {
    const first = recorder(), second = recorder(), firstPlayer = player(), secondPlayer = player();
    audio.start.mockResolvedValueOnce(first).mockResolvedValueOnce(second);
    audio.player.mockReturnValueOnce(firstPlayer).mockReturnValueOnce(secondPlayer);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    const previous = Socket.instances[0];
    act(() => { previous.open(); previous.receive({ type: "ended", reason: "learner_ended", follow_ups: [] }); });
    await userEvent.click(screen.getByRole("button", { name: "Start again" }));
    expect(previous.close).toHaveBeenCalledTimes(1);
    const current = Socket.instances[1];
    act(() => { current.open(); current.receive({ type: "ready", max_seconds: 60, language_code: "en", topic: "Current video" }); });
    act(() => { previous.closed(); previous.receive(new Int16Array(4).buffer); previous.receive({ type: "error", code: "realtime_unavailable" }); });
    expect(second.dispose).not.toHaveBeenCalled();
    expect(secondPlayer.close).not.toHaveBeenCalled();
    expect(secondPlayer.enqueue).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "End" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("can retry a microphone failure in the current screen", async () => {
    audio.start.mockRejectedValueOnce(new Error("synthetic microphone failure")).mockResolvedValueOnce(recorder());
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    expect(screen.getByRole("alert")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Start again" }));
    expect(Socket.instances).toHaveLength(1);
    act(() => { Socket.instances[0].open(); Socket.instances[0].receive({ type: "ready", max_seconds: 60, language_code: "en", topic: "Retry" }); });
    expect(screen.getByRole("button", { name: "End" })).toBeVisible();
  });
});
