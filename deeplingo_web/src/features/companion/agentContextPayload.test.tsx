import { useState } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { AgentScreen } from "./AgentScreen";
import { AgentConversation } from "./AgentConversation";

const VIDEO = "33333333-3333-4333-8333-333333333333";
const SEGMENT = "44444444-4444-4444-8444-444444444444";
const BOOK = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
vi.mock("../../lib/audio/pcmRecorder", () => ({ startPcmRecorder: vi.fn(async () => ({ takeChunk: vi.fn(), dispose: vi.fn() })) }));
vi.mock("../../lib/audio/pcmPlayer", () => ({ createPcmPlayer: () => ({ enqueue: vi.fn(), flush: vi.fn(), close: vi.fn() }) }));

class Socket {
  static OPEN = 1;
  static last: Socket;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor() { Socket.last = this; }
  send(data: string) { this.sent.push(data); }
  close() { this.readyState = 3; this.onclose?.({ code: 1000 }); }
}
afterEach(() => vi.unstubAllGlobals());

function mount(path: string) {
  vi.stubGlobal("WebSocket", Socket);
  const start = vi.fn(() => new Promise(() => {}));
  const container = {
    config: { apiBaseUrl: "https://api.example.com" },
    gateway: { currentSession: vi.fn(async () => ({ userId: "synthetic", accessToken: "dummy" })) },
    companion: { getAgentConsent: vi.fn(async () => ({ status: "granted" })), start },
    lists: { list: vi.fn(async () => [BOOK, OTHER].map((id, index) => ({ id, name: `Book ${index}`, languageCode: "en" }))) },
    words: { list: vi.fn(async () => ({ words: [] })) },
  } as unknown as AppContainer;
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ContainerProvider container={container}><MemoryRouter initialEntries={[path]}>
      <AgentScreen />
    </MemoryRouter></ContainerProvider>
  </QueryClientProvider>);
  return start;
}

it("sends the expanded video sentence in the full-page Live start message", async () => {
  mount(`/agent?entry=video&item=${VIDEO}&segment=${SEGMENT}`);
  await userEvent.click(await screen.findByRole("button", { name: "Start talking" }));
  const socket = Socket.last;
  act(() => { socket.readyState = Socket.OPEN; socket.onopen?.(); });
  const message = socket.sent.map(raw => JSON.parse(raw)).find(item => item.type === "start");
  expect(message).toMatchObject({ entry: "video", library_item_id: VIDEO, segment_id: SEGMENT });
});

it("continues the same video conversation as typed or recorded turns when live voice fails", async () => {
  const start = mount(`/agent?entry=video&item=${VIDEO}&segment=${SEGMENT}`);
  await userEvent.click(await screen.findByRole("button", { name: "Start talking" }));
  act(() => { Socket.last.onclose?.({ code: 1011 }); });
  await userEvent.click(await screen.findByRole("button", { name: "Type or record instead" }));
  await waitFor(() => expect(start).toHaveBeenCalledWith("video", VIDEO, { segment_id: SEGMENT }));
});

it("has no separate conversation mode: an old mode=conversation link opens the voice screen", async () => {
  const start = mount(`/agent?mode=conversation&entry=video&item=${VIDEO}`);
  await waitFor(() => expect(document.body.textContent).toMatch(/Start talking|Connecting to Tata|Listening/));
  expect(start).not.toHaveBeenCalled();
  expect(screen.queryByRole("textbox", { name: "Type your answer" })).toBeNull();
});

it("keeps a newly selected notebook when switching the panel to recorded turns", async () => {
  // Use a small parent like AgentDock, which owns the selection through both transports.
  const start = vi.fn(() => new Promise(() => {}));
  const container = { companion: { getAgentConsent: vi.fn(async () => ({ status: "granted" })), start },
    lists: { list: vi.fn(async () => [BOOK, OTHER].map((id, index) => ({ id, name: `Book ${index}`, languageCode: "en" }))) },
  } as unknown as AppContainer;
  function Panel() {
    const [topic, setTopic] = useState(BOOK);
    return <AgentConversation entry="home" item={null} topicId={topic} onTopicChange={setTopic} />;
  }
  render(<QueryClientProvider client={new QueryClient()}><ContainerProvider container={container}>
    <MemoryRouter><Panel /></MemoryRouter>
  </ContainerProvider></QueryClientProvider>);
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Topic" }), OTHER);
  await userEvent.click(screen.getByRole("button", { name: "Use recorded turns" }));
  await userEvent.click(await screen.findByRole("button", { name: "Start talking" }));
  await waitFor(() => expect(start).toHaveBeenCalledWith("home", null, { topic_id: OTHER }));
});
