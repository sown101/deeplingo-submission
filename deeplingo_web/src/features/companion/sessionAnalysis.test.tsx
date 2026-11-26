import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { SessionAnalysis } from "./SessionAnalysis";
import { parseSessionAnalysis } from "./sessionAnalysisModels";
import { parseRealtimeEvent, RealtimeSession } from "./realtimeClient";

const ID = "11111111-1111-4111-8111-111111111111";
const WORD = "22222222-2222-4222-8222-222222222222";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mount(get: ReturnType<typeof vi.fn>, status: "queued" | "unavailable" = "queued") {
  const query = new QueryClient({ defaultOptions: { queries: { gcTime: 0, retry: false } } });
  const invalidate = vi.spyOn(query, "invalidateQueries");
  render(<QueryClientProvider client={query}><ContainerProvider container={{ client: { get } } as unknown as AppContainer}>
    <SessionAnalysis analysis={{ session_id: ID, status }} />
  </ContainerProvider></QueryClientProvider>);
  return { query, invalidate };
}

describe("L2 session analysis", () => {
  it.each(["queued", "projecting"])("polls %s, shows support level and refreshes word/coverage views after completion", async (pendingStatus) => {
    const get = vi.fn().mockResolvedValueOnce({ session_id: ID, status: pendingStatus, events: [] })
      .mockResolvedValue({ session_id: ID, status: "completed", events: [{ concept_id: WORD, text: "分享", kind: "framed_use" }] });
    const { query, invalidate } = mount(get);
    expect(screen.getByRole("status")).toHaveTextContent("Reviewing");
    await screen.findByText(/Used with support/, {}, { timeout: 3000 });
    expect(get).toHaveBeenCalledWith(`/learner/me/speaking-sessions/${ID}`);
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["my-words"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["video-coverage"] });
    query.clear();
  });

  it("does not present no evidence as a failure or invent progress", async () => {
    const get = vi.fn().mockResolvedValue({ session_id: ID, status: "completed", events: [] });
    const { query } = mount(get);
    await screen.findByText("No reliable word use was confirmed in this session.");
    expect(screen.queryByText(/Used independently/)).not.toBeInTheDocument();
    query.clear();
  });

  it.each(["failed", "expired"])("shows %s without fetching the raw transcript", async (status) => {
    const get = vi.fn().mockResolvedValue({ session_id: ID, status, events: [] });
    const { query } = mount(get);
    await screen.findByText(/could not be completed/);
    expect(get).toHaveBeenCalledTimes(1);
    query.clear();
  });

  it("unavailable enqueue does not poll a nonexistent session", () => {
    const get = vi.fn(); const { query } = mount(get, "unavailable");
    expect(screen.getByText(/could not be completed/)).toBeVisible();
    expect(get).not.toHaveBeenCalled(); query.clear();
  });

  it.each([
    { session_id: "bad", status: "completed", events: [] },
    { session_id: ID, status: "scored", events: [] },
    { session_id: ID, status: "completed", events: [{ concept_id: WORD, text: "travel", kind: "mastered" }] },
  ])("rejects malformed/unrecognised analysis data", (raw) => {
    expect(() => parseSessionAnalysis(raw)).toThrow();
  });

  it("parses new end metadata while retaining the old end protocol", () => {
    expect(parseRealtimeEvent(JSON.stringify({ type: "ended", reason: "learner_ended", follow_ups: [] })))
      .toEqual({ type: "ended", reason: "learner_ended", follow_ups: [] });
    expect(parseRealtimeEvent(JSON.stringify({ type: "ended", analysis: { session_id: ID, status: "queued" } })))
      .toMatchObject({ analysis: { session_id: ID, status: "queued" } });
  });

  it("sends only the entry, the day and what the server needs to check: no consent flag, no chosen words", () => {
    class Socket {
      static last: Socket;
      onopen: (() => void) | null = null;
      send = vi.fn();
      constructor(public url: string) { Socket.last = this; }
    }
    vi.stubGlobal("WebSocket", Socket);
    const session = new RealtimeSession("wss://example.invalid/live", { onEvent: vi.fn(), onAudio: vi.fn(), onClosed: vi.fn() });
    session.open("fake.access.token", { entry: "home", library_item_id: null, day: "2026-10-27", topic_id: WORD });
    Socket.last.onopen?.();
    const start = JSON.parse(Socket.last.send.mock.calls[1][0]);
    expect(start).toEqual({ type: "start", entry: "home", day: "2026-10-27", topic_id: WORD });
    expect(Socket.last.url).not.toContain("fake.access.token");
  });
});
