import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { AgentScreen } from "./AgentScreen";

const recorder = { takeChunk: vi.fn(() => new Int16Array([1, 2])), dispose: vi.fn() };
const player = { enqueue: vi.fn(), flush: vi.fn(), close: vi.fn() };
vi.mock("../../lib/audio/pcmRecorder", async original => ({
  ...await original<typeof import("../../lib/audio/pcmRecorder")>(), startPcmRecorder: vi.fn(async () => recorder),
}));
vi.mock("../../lib/audio/pcmPlayer", () => ({ createPcmPlayer: () => player }));

class Socket {
  static OPEN = 1;
  static last: Socket | null = null;
  readyState = 0;
  binaryType = "blob";
  sent: (string | ArrayBuffer)[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor() { Socket.last = this; }
  send(data: string | ArrayBuffer) { this.sent.push(data); }
  close(code = 1000) { this.readyState = 3; this.onclose?.({ code }); }
  receive(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
}

beforeEach(() => { vi.stubGlobal("WebSocket", Socket); Socket.last = null; vi.clearAllMocks(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function mount(path = "/agent?mode=voice") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["language-profile"], { learning_language: "en" });
  const words = { list: vi.fn(async () => ({ words: [
    { conceptId: "1", text: "airport", languageCode: "en", saved: true, status: "active", rung: 0 },
    { conceptId: "2", text: "paused word", languageCode: "en", saved: true, status: "suspended", rung: 0 },
    { conceptId: "3", text: "unsaved word", languageCode: "en", saved: false, status: "active", rung: 0 },
  ] })) };
  const container = {
    config: { apiBaseUrl: "https://api.example.com" },
    gateway: { currentSession: vi.fn(async () => ({ userId: "u1", accessToken: "dummy" })) },
    companion: { getAgentConsent: vi.fn(async () => ({ status: "granted" })), scenarios: vi.fn(async () => [
      { id: "hotel", title: "Missing reservation", context: "The reservation is missing.",
        roles: ["Guest", "Receptionist"], goals: ["Confirm your booking.", "Offer a solution."] },
    ]) },
    lists: { list: vi.fn(async () => [{ id: "book", name: "Travel", languageCode: "en" }]) }, words,
  } as unknown as AppContainer;
  render(<StrictMode><QueryClientProvider client={client}><ContainerProvider container={container}>
    <MemoryRouter initialEntries={[path]}><AgentScreen /></MemoryRouter>
  </ContainerProvider></QueryClientProvider></StrictMode>);
  return { words };
}

it("starts the conversation when Agent opens, with no mode buttons", async () => {
  const { words } = mount();
  await screen.findByText("airport");
  expect(screen.queryByText("paused word")).not.toBeInTheDocument();
  expect(screen.queryByText("unsaved word")).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "Agent modes" })).toBeNull();
  await waitFor(() => expect(Socket.last).not.toBeNull());
  expect(words.list).toHaveBeenCalledWith("en", undefined);
});

it("shows the agent's tasks and activity button during the conversation", async () => {
  mount();
  await waitFor(() => expect(Socket.last).not.toBeNull());
  const socket = Socket.last!;
  act(() => { socket.readyState = 1; socket.onopen?.(); });
  act(() => socket.receive({ type: "ready", max_seconds: 60, language_code: "en", topic: "Travel" }));
  act(() => socket.receive({ type: "offer", kind: "grammar" }));
  expect(await screen.findByRole("link", { name: "Grammar" })).toHaveAttribute("href", "/words/lists?tab=grammar");
});

it("shows help on screen while the conversation is running", async () => {
  mount();
  await waitFor(() => expect(Socket.last).not.toBeNull());
  const socket = Socket.last!;
  act(() => { socket.readyState = 1; socket.onopen?.(); });
  act(() => socket.receive({ type: "ready", max_seconds: 60, language_code: "en", topic: "Travel" }));
  expect(await screen.findByRole("button", { name: "Hint" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Ideas" })).toBeVisible();
  act(() => socket.receive({ type: "suggestions", items: [{ sentence: "I would like a window seat.", explanation: "Asking politely." }] }));
  await waitFor(() => expect(document.querySelector(".agent-live-help")).toHaveTextContent("I would like a window seat."));
});

it("ends on the summary, without the word chips or the opening tasks", async () => {
  mount();
  await screen.findByText("airport");
  await waitFor(() => expect(Socket.last).not.toBeNull());
  const socket = Socket.last!;
  act(() => { socket.readyState = 1; socket.onopen?.(); });
  act(() => socket.receive({ type: "ready", max_seconds: 60, language_code: "en", topic: "Travel" }));
  act(() => socket.receive({ type: "offer", kind: "grammar" }));
  expect(await screen.findByRole("link", { name: "Grammar" })).toBeInTheDocument();
  act(() => socket.receive({ type: "ended", reason: "learner_ended", follow_ups: [] }));
  await waitFor(() => expect(screen.queryByText("airport")).not.toBeInTheDocument());
  expect(screen.queryByRole("link", { name: "Grammar" })).not.toBeInTheDocument();
});

it("swaps roles before starting and sends only the selected server scenario and role flag", async () => {
  mount("/agent?mode=voice&practice=roleplay");
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Your role" }), "1");
  expect(screen.getByText(/Offer a solution/)).toBeVisible();
  expect(Socket.last).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Start talking" }));
  const socket = Socket.last!;
  act(() => { socket.readyState = 1; socket.onopen?.(); });
  const start = socket.sent.filter((item): item is string => typeof item === "string").map(item => JSON.parse(item)).find(item => item.type === "start");
  expect(start).toMatchObject({ scenario_id: "hotel", swap_roles: true });
  expect(start).not.toHaveProperty("roles");
  expect(start).not.toHaveProperty("prompt");
});

it("pauses PCM transmission from the design's microphone button and resumes only on another press", async () => {
  mount();
  await waitFor(() => expect(Socket.last).not.toBeNull());
  const socket = Socket.last!;
  act(() => { socket.readyState = 1; socket.onopen?.(); });
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  act(() => socket.receive({ type: "ready", max_seconds: 60, language_code: "en", topic: "Travel" }));
  act(() => vi.advanceTimersByTime(100));
  const count = () => socket.sent.filter(message => typeof message !== "string").length;
  expect(count()).toBeGreaterThan(0);
  await userEvent.click(screen.getByRole("button", { name: "Pause microphone" }));
  const before = count();
  act(() => vi.advanceTimersByTime(500));
  expect(count()).toBe(before);
  await userEvent.click(screen.getByRole("button", { name: "Resume microphone" }));
  act(() => vi.advanceTimersByTime(100));
  expect(count()).toBeGreaterThan(before);
  await userEvent.click(screen.getByRole("button", { name: "End" }));
  expect(recorder.dispose).toHaveBeenCalled();
  act(() => {
    socket.receive({ type: "ended", reason: "learner_ended", follow_ups: [] });
    socket.close();
  });
  expect(screen.getByRole("button", { name: "Start again" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
