import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { parseRealtimeEvent, realtimeUrl, RealtimeSession, speechOnly } from "./realtimeClient";
import { RealtimeScreen } from "./RealtimeScreen";

const recorder = { takeChunk: vi.fn(() => new Int16Array(1600)), stop: vi.fn(), dispose: vi.fn() };
const player = { enqueue: vi.fn(), flush: vi.fn(), close: vi.fn() };

vi.mock("../../lib/audio/pcmRecorder", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/audio/pcmRecorder")>()),
  startPcmRecorder: vi.fn(async () => recorder),
}));
vi.mock("../../lib/audio/pcmPlayer", () => ({ createPcmPlayer: () => player }));

class FakeSocket {
  static OPEN = 1;
  static last: FakeSocket | null = null;
  readyState = 0;
  binaryType = "blob";
  sent: (string | ArrayBuffer)[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.last = this;
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  // test helpers
  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  receive(data: unknown) {
    this.onmessage?.({ data: typeof data === "string" || data instanceof ArrayBuffer ? data : JSON.stringify(data) });
  }

  json(): Record<string, unknown>[] {
    return this.sent.filter((item): item is string => typeof item === "string").map((item) => JSON.parse(item));
  }
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeSocket);
  FakeSocket.last = null;
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("realtime event parsing", () => {
  it("accepts the backend events", () => {
    expect(parseRealtimeEvent(JSON.stringify({ type: "ready", max_seconds: 600, input_sample_rate: 16000,
      language_code: "en", topic: "Summer jobs" })))
      .toEqual({ type: "ready", max_seconds: 600, topic: "Summer jobs", language_code: "en" });
    expect(parseRealtimeEvent(JSON.stringify({ type: "audio_format", sample_rate: 24000, encoding: "pcm_s16le",
      channels: 1 }))).toEqual({ type: "audio_format", sample_rate: 24000 });
    expect(parseRealtimeEvent(JSON.stringify({ type: "correction", quote: "I goed", suggestion: "I went",
      note: "Thử lại nhé." }))?.type).toBe("correction");
    const hint = parseRealtimeEvent(JSON.stringify({ type: "hint", question: "Bạn thích gì?", frame: "I like ___.",
      frame_reason: "Dùng like.", model_sentence: "I like tea.", items: [{ id: "c1", text: "tea", meaning: "trà" },
        { id: "", text: "bad" }] }));
    expect(hint?.type === "hint" && hint.hint.items).toEqual([{ id: "c1", text: "tea", meaning: "trà" }]);
  });

  it("reads notebook notices and save offers strictly", () => {
    expect(parseRealtimeEvent(JSON.stringify({ type: "study_request", kind: "grammar_redo", item: "en.a1.x", title: null })))
      .toEqual({ type: "study_request", request: { kind: "grammar_redo", item: "en.a1.x", title: null } });
    expect(parseRealtimeEvent(JSON.stringify({ type: "study_request", kind: "delete_account", item: "x" }))).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "save_word", word: "market", headword: "market" }))).toBeNull();
    const hint = parseRealtimeEvent(JSON.stringify({ type: "hint", level: 7, question: "Q?", items: [] }));
    expect(hint?.type === "hint" && hint.hint.level).toBe(1);
  });

  it("reads the opening choices and a turn's pronunciation strictly", () => {
    expect(parseRealtimeEvent(JSON.stringify({ type: "choices", items: [{ id: "words", count: 5 }, { id: "free" },
      { id: "delete_account" }] }))).toEqual({ type: "choices", items: [{ id: "words", count: 5 }, { id: "free", count: null }] });
    expect(parseRealtimeEvent(JSON.stringify({ type: "choices", items: [{ id: "nope" }] }))).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "pronunciation", turn: 2, overall: 81, weak_words: ["think", 7, ""] })))
      .toEqual({ type: "pronunciation", score: { turn: 2, overall: 81, weak_words: ["think"] } });
    expect(parseRealtimeEvent(JSON.stringify({ type: "pronunciation", turn: 1, overall: 140, weak_words: [] }))).toBeNull();
  });

  it("never shows a provider marker as speech", () => {
    expect(speechOnly("<no speech>{pause}")).toBe("");
    expect(speechOnly("Hello <noise> there")).toBe("Hello  there");
    expect(speechOnly("Is 3 < 5? yes")).toBe("Is 3 < 5? yes");
    expect(speechOnly("Almost <no sp")).toBe("Almost ");
  });

  it("drops malformed, unknown or unsafe events", () => {
    expect(parseRealtimeEvent("not json")).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "surprise" }))).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "audio_format", sample_rate: 1 }))).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "correction", quote: "x", suggestion: "" }))).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "transcript", role: "system", text: "x" }))).toBeNull();
    const lookup = parseRealtimeEvent(JSON.stringify({ type: "looked_up", word: "farm", entries: [{
      headword: "farm", senses: [{ text: "A place for crops." }], source_name: "Wiktionary",
      source_url: "javascript:alert(1)" }] }));
    expect(lookup?.type === "looked_up" && lookup.lookup.entries[0].source_url).toBeNull();
  });

  it("builds a websocket URL from the API base", () => {
    expect(realtimeUrl("https://api.example.com/")).toBe("wss://api.example.com/learner/me/companion/realtime");
    expect(realtimeUrl("http://localhost:8000")).toBe("ws://localhost:8000/learner/me/companion/realtime");
  });
});

describe("realtime session", () => {
  it("sends the token in the first message, never in the URL, and splits audio into one-second frames", () => {
    const session = new RealtimeSession("wss://api.example.com/learner/me/companion/realtime",
      { onEvent: vi.fn(), onAudio: vi.fn(), onClosed: vi.fn() });
    session.open("a.b.c", { entry: "home", library_item_id: null, day: "2026-10-17" });
    const socket = FakeSocket.last!;
    socket.open();
    expect(socket.url).not.toContain("a.b.c");
    expect(socket.json()).toEqual([{ type: "auth", token: "a.b.c" },
      { type: "start", entry: "home", day: "2026-10-17" }]);
    session.sendAudio(new Int16Array(40_000));
    const frames = socket.sent.filter((item) => item instanceof ArrayBuffer) as ArrayBuffer[];
    expect(frames.map((frame) => frame.byteLength)).toEqual([32_000, 32_000, 16_000]);
  });
});

describe("realtime session reattach", () => {
  it("replaces a socket that dropped by itself and asks for the events it missed", () => {
    vi.useFakeTimers();
    const onClosed = vi.fn();
    const onEvent = vi.fn();
    const session = new RealtimeSession("wss://api.example.com/learner/me/companion/realtime",
      { onEvent, onAudio: vi.fn(), onClosed });
    session.open("a.b.c", { entry: "home", library_item_id: null, day: "2026-10-17" });
    const first = FakeSocket.last!;
    first.open();
    first.receive({ type: "ready", session_id: "s-1", max_seconds: 600, topic: "Travel", language_code: "en" });
    first.receive({ type: "transcript", role: "companion", text: "Hi!" });
    first.close(1006); // the network dropped it
    expect(onClosed).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300);
    const second = FakeSocket.last!;
    expect(second).not.toBe(first);
    second.open();
    expect(second.json()).toEqual([{ type: "auth", token: "a.b.c" }, { type: "resume", session_id: "s-1", last_seq: 2 }]);
    second.receive({ type: "transcript", role: "companion", text: "Still there?" });
    expect(onEvent).toHaveBeenLastCalledWith({ type: "transcript", role: "companion", text: "Still there?" });
  });

  it("does not reattach after the conversation ended, after a refusal, or without a session id", () => {
    vi.useFakeTimers();
    const onClosed = vi.fn();
    const session = new RealtimeSession("wss://x/learner/me/companion/realtime",
      { onEvent: vi.fn(), onAudio: vi.fn(), onClosed });
    session.open("a.b.c", { entry: "home", library_item_id: null, day: "2026-10-17" });
    const socket = FakeSocket.last!;
    socket.open();
    socket.receive({ type: "ready", max_seconds: 600, topic: "Travel", language_code: "en" });
    socket.close(1006);
    vi.advanceTimersByTime(5000);
    expect(FakeSocket.last).toBe(socket);
    expect(onClosed).toHaveBeenCalledWith(1006);
  });
});

const GRANTED = { status: "granted", decided_at: "2026-10-29T10:00:00Z" };

const saveWord = vi.fn().mockResolvedValue({});
const undoEdit = vi.fn().mockResolvedValue({});

function renderAt(path: string, companion: unknown = { getAgentConsent: vi.fn().mockResolvedValue(GRANTED) },
  lists: unknown[] = []) {
  const container = {
    config: { apiBaseUrl: "https://api.example.com" },
    gateway: { currentSession: vi.fn().mockResolvedValue({ userId: "u1", accessToken: "a.b.c" }) },
    plan: { undoEdit },
    companion,
    lists: { list: vi.fn().mockResolvedValue(lists) },
    words: { save: saveWord },
  } as unknown as AppContainer;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ContainerProvider container={container}>
        <MemoryRouter initialEntries={[path]}>
          <Routes><Route path="/companion/realtime" element={<RealtimeScreen />} /></Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

describe("RealtimeScreen", () => {
  it("lists the saved words of the learning language once the profile has loaded, not only if it was cached", async () => {
    const list = vi.fn().mockResolvedValue({ words: [] });
    const container = {
      config: { apiBaseUrl: "https://api.example.com" },
      gateway: { currentSession: vi.fn().mockResolvedValue({ userId: "u1", accessToken: "a.b.c" }) },
      companion: { getAgentConsent: vi.fn().mockResolvedValue(GRANTED) },
      lists: { list: vi.fn().mockResolvedValue([]) },
      words: { list, save: saveWord },
      onboarding: { loadProfile: vi.fn().mockResolvedValue({ learning_language: "zh", support_language: "vi" }) },
    } as unknown as AppContainer;
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ContainerProvider container={container}>
          <MemoryRouter initialEntries={["/companion/realtime?entry=home"]}>
            <Routes><Route path="/companion/realtime" element={<RealtimeScreen fullPage />} /></Routes>
          </MemoryRouter>
        </ContainerProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(list).toHaveBeenCalledWith("zh", undefined));
  });

  it("runs a conversation: transcripts, audio, hint, correction, interruption and the end", async () => {
    renderAt("/companion/realtime?entry=home");
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    const socket = FakeSocket.last!;
    act(() => socket.open());
    act(() => socket.receive({ type: "ready", max_seconds: 600, language_code: "en", topic: "Summer jobs" }));
    expect(screen.getByText("Topic: Summer jobs")).toBeInTheDocument();

    act(() => {
      socket.receive({ type: "audio_format", sample_rate: 24000 });
      socket.receive(new Int16Array(4).buffer);
      socket.receive({ type: "transcript", role: "companion", text: "Hi! Do you " });
      socket.receive({ type: "transcript", role: "companion", text: "like summer?" });
      socket.receive({ type: "turn_complete" });
      socket.receive({ type: "transcript", role: "learner", text: "I goed to work." });
      socket.receive({ type: "correction", quote: "I goed", suggestion: "I went", note: "Thử lại nhé." });
      socket.receive({ type: "interrupted" });
    });
    expect(player.enqueue).toHaveBeenCalledWith(expect.any(Int16Array), 24000);
    expect(player.flush).toHaveBeenCalled();
    expect(screen.getByText("Hi! Do you like summer?")).toBeInTheDocument();
    expect(screen.getByText("I went", { exact: false })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Hint" }));
    expect(socket.json()).toContainEqual({ type: "help" });
    act(() => socket.receive({ type: "hint", question: "Bạn làm gì?", frame: "I worked at ___.",
      frame_reason: "Dùng quá khứ.", model_sentence: "I worked at a farm.", items: [] }));
    expect(screen.getByText("Example: I worked at a farm.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "End" }));
    expect(socket.json()).toContainEqual({ type: "end" });
    act(() => {
      socket.receive({ type: "ended", reason: "learner_ended", follow_ups: [] });
      socket.close(1000);
    });
    expect(screen.getByText("You ended the conversation.")).toBeInTheDocument();
    expect(recorder.dispose).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Start again" })).toBeInTheDocument();
  });

  it("explains a refusal for an account without access", async () => {
    renderAt("/companion/realtime?entry=home");
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    const socket = FakeSocket.last!;
    act(() => {
      socket.open();
      socket.receive({ type: "error", code: "realtime_not_available", message: "x" });
      socket.close(4403);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("not open for this account");
  });

  it("reports a dropped connection without blaming the learner", async () => {
    renderAt("/companion/realtime?entry=home");
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    act(() => FakeSocket.last!.close(1006));
    expect(screen.getByRole("alert")).toHaveTextContent("unavailable right now");
  });

  it("rejects an invalid link", () => {
    renderAt("/companion/realtime?entry=video&item=nope");
    expect(screen.getByRole("alert")).toHaveTextContent("not valid");
  });

  async function startButton() {
    return screen.findByRole("button", { name: "Start" });
  }

  it.each([
    ["not decided", { status: "ask", decided_at: null }],
    ["revoked", { status: "revoked", decided_at: "2026-10-29T10:00:00Z" }],
  ])("asks for the voice consent before the first conversation instead of starting one (%s)", async (_name, status) => {
    const companion = { getAgentConsent: vi.fn().mockResolvedValue(status), setAgentConsent: vi.fn().mockResolvedValue(GRANTED) };
    renderAt("/companion/realtime?entry=home", companion);
    await userEvent.click(await screen.findByRole("button", { name: "Allow voice processing" }));
    expect(companion.setAgentConsent).toHaveBeenCalledWith(true);
    await userEvent.click(await startButton());
    expect(FakeSocket.last).not.toBeNull();
  });

  it("asks once, after voice is allowed, whether to keep transcripts; either answer is saved and never blocks starting", async () => {
    for (const answer of ["Allow keeping transcripts", "Not now"]) {
      const ask = { status: "ask", decided_at: null, active: false };
      const decided = { status: answer === "Not now" ? "revoked" : "granted", decided_at: "2026-11-07T10:00:00Z", active: answer !== "Not now" };
      const companion = { getAgentConsent: vi.fn().mockResolvedValue(GRANTED),
        getTranscriptConsent: vi.fn().mockResolvedValue(ask), setTranscriptConsent: vi.fn().mockResolvedValue(decided) };
      renderAt("/companion/realtime?entry=home", companion);
      expect(await screen.findByText("Keep transcripts for calibration and review?")).toBeInTheDocument();
      expect(await startButton()).toBeEnabled();
      await userEvent.click(screen.getByRole("button", { name: answer }));
      await waitFor(() => expect(screen.queryByText("Keep transcripts for calibration and review?")).not.toBeInTheDocument());
      expect(companion.setTranscriptConsent).toHaveBeenCalledWith(answer !== "Not now");
      cleanup();
    }
  });

  it("does not ask about transcripts before voice is allowed", async () => {
    const getTranscriptConsent = vi.fn().mockResolvedValue({ status: "ask", decided_at: null, active: false });
    renderAt("/companion/realtime?entry=home", { getAgentConsent: vi.fn().mockResolvedValue({ status: "ask", decided_at: null }), getTranscriptConsent });
    await screen.findByRole("button", { name: "Allow voice processing" });
    expect(screen.queryByText("Keep transcripts for calibration and review?")).not.toBeInTheDocument();
    expect(getTranscriptConsent).not.toHaveBeenCalled();
  });

  it("does not open the microphone or a connection while the consent is missing", async () => {
    renderAt("/companion/realtime?entry=home", { getAgentConsent: vi.fn().mockResolvedValue({ status: "ask", decided_at: null }) });
    await screen.findByRole("button", { name: "Allow voice processing" });
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(FakeSocket.last).toBeNull();
  });

  it("shows a retryable error, never a start button, when the consent cannot be read", async () => {
    const getAgentConsent = vi.fn().mockRejectedValueOnce(new Error("private detail")).mockResolvedValue(GRANTED);
    renderAt("/companion/realtime?entry=home", { getAgentConsent });
    expect(await screen.findByText("Your voice settings could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry voice settings" }));
    expect(await startButton()).toBeInTheDocument();
  });

  it("explains a refusal because the consent was revoked", async () => {
    renderAt("/companion/realtime?entry=home");
    await userEvent.click(await startButton());
    act(() => {
      FakeSocket.last!.open();
      FakeSocket.last!.receive({ type: "error", code: "voice_consent_required", message: "x" });
      FakeSocket.last!.close(4403);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Allow voice processing in Profile");
  });

  it("sends no per-session consent flag and no chosen words: the server holds the consent and picks the words", async () => {
    renderAt("/companion/realtime?entry=home");
    await userEvent.click(await startButton());
    act(() => FakeSocket.last!.open());
    const start = FakeSocket.last!.json().find((message) => message.type === "start")!;
    expect(Object.keys(start).sort()).toEqual(["day", "entry", "type"]);
  });

  it("lets the learner change the topic to one of their own notebooks, and offers none for a video", async () => {
    const books = [{ id: "99999999-0000-4000-8000-000000000001", languageCode: "en", name: "Travel", description: null,
      wordCount: 4, waitingCount: 0 }];
    renderAt("/companion/realtime?entry=home", undefined, books);
    await userEvent.selectOptions(await screen.findByLabelText("Topic"), "Travel");
    await userEvent.click(await startButton());
    act(() => FakeSocket.last!.open());
    const start = FakeSocket.last!.json().find((message) => message.type === "start")!;
    expect(start.topic_id).toBe(books[0].id);
  });

  it("does not offer a topic for a video conversation", async () => {
    const books = [{ id: "99999999-0000-4000-8000-000000000001", languageCode: "en", name: "Travel", description: null,
      wordCount: 4, waitingCount: 0 }];
    renderAt(`/companion/realtime?entry=video&item=${"11111111-1111-4111-8111-111111111111"}`, undefined, books);
    await startButton();
    expect(screen.queryByLabelText("Topic")).not.toBeInTheDocument();
  });

  async function startLive() {
    renderAt("/companion/realtime?entry=home");
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    const socket = FakeSocket.last!;
    act(() => { socket.open(); socket.receive({ type: "ready", max_seconds: 600, language_code: "en", topic: "Summer" }); });
    return socket;
  }

  it("steps the Hint button through the server's help ladder and starts over when the learner speaks", async () => {
    const socket = await startLive();
    expect(screen.getByRole("button", { name: "Hint" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hint" }));
    expect(socket.json().filter((message) => (message as { type?: string }).type === "help")).toHaveLength(1);
    act(() => socket.receive({ type: "hint", level: 1, question: "Bạn làm gì?", frame: null, frame_reason: null,
      model_sentence: null, items: [{ id: "c1", text: "farm", meaning: "nông trại" }] }));
    expect(screen.getByRole("button", { name: "More help" })).toBeInTheDocument();
    expect(screen.queryByText(/Example:/)).not.toBeInTheDocument();
    act(() => socket.receive({ type: "hint", level: 2, question: "Bạn làm gì?", frame: "I worked at ___.",
      frame_reason: "Dùng quá khứ.", model_sentence: null, items: [] }));
    expect(screen.getByRole("button", { name: "Show a full example" })).toBeInTheDocument();
    act(() => socket.receive({ type: "transcript", role: "learner", text: "I worked on a farm." }));
    expect(screen.getByRole("button", { name: "Hint" })).toBeInTheDocument();
  });

  it("shows a hint the server opened because the learner hesitated, without a tap", async () => {
    const socket = await startLive();
    act(() => socket.receive({ type: "hint", level: 1, auto: true, question: "Bạn uống gì buổi sáng?", frame: null,
      frame_reason: null, model_sentence: null, items: [{ id: "c1", text: "coffee", meaning: "cà phê" }] }));
    expect(socket.json().filter((message) => (message as { type?: string }).type === "help")).toHaveLength(0);
    expect(screen.getByText("Bạn uống gì buổi sáng?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "More help" })).toBeInTheDocument();
  });

  it("shows one hint card that grows with the help step and goes when the learner answers", async () => {
    const socket = await startLive();
    act(() => socket.receive({ type: "hint", level: 1, question: "Bạn uống gì?", frame: null, frame_reason: null,
      model_sentence: null, items: [{ id: "c1", text: "coffee", meaning: "cà phê" }] }));
    act(() => socket.receive({ type: "hint", level: 2, question: "Bạn uống gì?", frame: "I drink ___.", frame_reason: "Dùng drink.",
      model_sentence: null, items: [{ id: "c1", text: "coffee", meaning: "cà phê" }] }));
    expect(screen.getAllByRole("region", { name: "Hint" })).toHaveLength(1);
    expect(screen.getAllByText("Bạn uống gì?")).toHaveLength(1);
    expect(screen.getByText(/I drink ___\./)).toBeInTheDocument();
    act(() => socket.receive({ type: "hint", level: 3, question: "Bạn uống gì?", frame: "I drink ___.", frame_reason: "x",
      model_sentence: "I drink coffee.", items: [] }));
    expect(screen.getAllByRole("region", { name: "Hint" })).toHaveLength(1);
    expect(screen.getByText(/I drink coffee\./)).toBeInTheDocument();
    act(() => socket.receive({ type: "transcript", role: "learner", text: "I drink tea." }));
    expect(screen.queryByRole("region", { name: "Hint" })).not.toBeInTheDocument();
  });

  it("shows no line for a silence marker, and a turn's pronunciation beside the learner's line", async () => {
    const socket = await startLive();
    act(() => {
      socket.receive({ type: "transcript", role: "companion", text: "<no speech>{pause}" });
      socket.receive({ type: "transcript", role: "learner", text: "I like tea." });
      socket.receive({ type: "pronunciation", turn: 1, overall: 78, weak_words: ["tea"] });
    });
    expect(screen.queryByText(/no speech/)).not.toBeInTheDocument();
    expect(screen.queryByText("Companion:")).not.toBeInTheDocument();
    expect(screen.getByText("I like tea.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Pronunciation 78")).toBeInTheDocument();
    expect(screen.getByText("Say again: tea")).toBeInTheDocument();
  });

  it("offers the opening choices, sends the tapped one and removes them", async () => {
    const socket = await startLive();
    act(() => socket.receive({ type: "choices", items: [{ id: "words", count: 4 }, { id: "free", count: null }] }));
    await userEvent.click(screen.getByRole("button", { name: "Practise 4 words due today" }));
    expect(socket.json().filter((message) => (message as { type?: string }).type === "choose"))
      .toEqual([{ type: "choose", id: "words" }]);
    expect(screen.queryByRole("button", { name: "Chat about a topic I choose" })).not.toBeInTheDocument();
  });

  it("says when a corrected grammar point was put on the practise-again list", async () => {
    const socket = await startLive();
    act(() => {
      socket.receive({ type: "correction", quote: "I go", suggestion: "I went", note: "Dùng quá khứ." });
      socket.receive({ type: "study_request", kind: "grammar_redo", item: "en.a1.past_simple", title: "Past simple" });
    });
    expect(screen.getByText("Tata will remind you to practise this")).toBeInTheDocument();
    expect(screen.getByText("Past simple")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Do the grammar exercise" })).toHaveAttribute("href", "/words/lists?tab=grammar");
  });

  it("saves a looked-up word only when the learner taps Save", async () => {
    const socket = await startLive();
    act(() => socket.receive({ type: "save_word", word: "market", headword: "market", language_code: "en",
      entry_id: "e1", sense_id: "s1", meaning: "chợ" }));
    expect(saveWord).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Save to notebook" }));
    expect(saveWord).toHaveBeenCalledWith({ source: "dictionary", language_code: "en", entry_id: "e1", sense_id: "s1" });
    expect(await screen.findByText("Saved to your notebook.")).toBeInTheDocument();
  });

  it("shows an action card that opens a review with one button and never navigates by itself", async () => {
    const socket = await startLive();
    const word = "11111111-1111-4111-8111-111111111111";
    act(() => socket.receive({ type: "action", action: "open_review", language_code: "en", concept_ids: [word] }));
    expect(screen.getByText("Words to review: 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start review" })).toHaveAttribute("href", expect.stringContaining(`/review/en?types=choice&concepts=${word}`));
    expect(screen.getByText("Talk with your agent")).toBeInTheDocument();  // still on the agent screen
  });

  it("drops a malformed action event and undoes a change to today's tasks", async () => {
    const socket = await startLive();
    act(() => socket.receive({ type: "action", action: "open_review", language_code: "en", concept_ids: ["nope"] }));
    expect(screen.queryByRole("link", { name: "Start review" })).not.toBeInTheDocument();
    const item = "66666666-6666-4666-8666-666666666666";
    act(() => socket.receive({ type: "action", action: "today_edited", change: "removed", item_id: item, kind: "my_words",
      minutes: 3, title: null }));
    expect(screen.getByText("Removed from today's tasks")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(undoEdit).toHaveBeenCalledWith(item, "removed");
    expect(await screen.findByText("Undone")).toBeInTheDocument();
  });

  it("asks for ideas on request and shows the suggested sentences with their explanations", async () => {
    const socket = await startLive();
    await userEvent.click(screen.getByRole("button", { name: "Ideas" }));
    expect(socket.json()).toContainEqual({ type: "suggest" });
    act(() => socket.receive({ type: "suggestions", items: [
      { sentence: "I like flying.", explanation: "Nói bạn thích đi máy bay." },
      { sentence: "I want to visit Japan.", explanation: "Nói nơi bạn muốn đến." }] }));
    expect(screen.getByText("I like flying.")).toBeInTheDocument();
    expect(screen.getByText("Nói nơi bạn muốn đến.")).toBeInTheDocument();
  });

  it("ends with a plain summary: counts and words only, never a score", async () => {
    const socket = await startLive();
    act(() => socket.receive({ type: "ended", reason: "learner_ended", follow_ups: [],
      summary: { spoken_turns: 3, corrections: 1, hints: 2, suggestions: 1, words_to_reuse: ["farm", "harvest"] } }));
    const summary = screen.getByRole("region", { name: "Session summary" });
    expect(summary).toHaveTextContent("You spoke 3 times.");
    expect(summary).toHaveTextContent("1 correction");
    expect(summary).toHaveTextContent("Words to try again: farm, harvest");
    expect(summary).not.toHaveTextContent(/score|level|grade/i);
  });

  it("lists the words to practise saying, as words only", async () => {
    const socket = await startLive();
    act(() => socket.receive({ type: "ended", reason: "learner_ended", follow_ups: [],
      summary: { spoken_turns: 2, corrections: 0, hints: 0, suggestions: 0, words_to_reuse: [],
        weak_words: ["travel", "train"] } }));
    const summary = screen.getByRole("region", { name: "Session summary" });
    expect(summary).toHaveTextContent("Words to practise saying: travel, train");
    expect(summary).not.toHaveTextContent(/\d+\s*(%|\/)/);
  });
});

describe("help ladder and summary parsing", () => {
  it("reads the hint step and keeps it within 1 to 3", () => {
    const step = (level: unknown) => {
      const event = parseRealtimeEvent(JSON.stringify({ type: "hint", level, question: "Q?", items: [] }));
      return event?.type === "hint" ? event.hint.level : null;
    };
    expect([step(1), step(2), step(3), step(9), step("x"), step(undefined)]).toEqual([1, 2, 3, 1, 1, 1]);
  });

  it("keeps at most three well-formed suggestions", () => {
    const event = parseRealtimeEvent(JSON.stringify({ type: "suggestions", items: [
      { sentence: "A.", explanation: "a" }, { sentence: "", explanation: "b" }, { sentence: "C.", explanation: "c" },
      { sentence: "D.", explanation: "d" }, { sentence: "E.", explanation: "e" }] }));
    expect(event?.type === "suggestions" && event.items.map((item) => item.sentence)).toEqual(["A.", "C.", "D."]);
    expect(parseRealtimeEvent(JSON.stringify({ type: "suggestions", items: [] }))).toBeNull();
  });

  it("accepts only whole-number counts and short word names in a summary", () => {
    const ended = (summary: unknown) => parseRealtimeEvent(JSON.stringify({ type: "ended", reason: "x",
      follow_ups: [], summary }));
    const good = ended({ spoken_turns: 2, corrections: 0, hints: 1, suggestions: 0, words_to_reuse: ["farm"] });
    expect(good?.type === "ended" && good.summary).toEqual({ spoken_turns: 2, corrections: 0, hints: 1, suggestions: 0,
      words_to_reuse: ["farm"] });
    const withWeak = ended({ spoken_turns: 1, corrections: 0, hints: 0, suggestions: 0, words_to_reuse: [],
      weak_words: ["travel", "", "x".repeat(80), 7, "train"] });
    expect(withWeak?.type === "ended" && withWeak.summary?.weak_words).toEqual(["travel", "train"]);
    expect(good?.type === "ended" && good.summary?.weak_words).toBeUndefined();
    const bad = ended({ spoken_turns: "2", corrections: 0, hints: 1, suggestions: 0, words_to_reuse: [] });
    expect(bad?.type === "ended" && bad.summary).toBeUndefined();
  });
});

describe("grammar teaching in the conversation (FR-8.1)", () => {
  async function live() {
    renderAt("/companion/realtime?entry=home");
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    const socket = FakeSocket.last!;
    act(() => { socket.open(); socket.receive({ type: "ready", max_seconds: 600, language_code: "en", topic: "Summer" }); });
    return socket;
  }

  it("asks for a fuller explanation on request and labels it as not yet verified", async () => {
    const socket = await live();
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(socket.json()).toContainEqual({ type: "explain" });
    act(() => socket.receive({ type: "grammar", explanation: "Có yesterday nên dùng quá khứ.", example: "I went there.",
      unverified: true }));
    const card = screen.getByRole("region", { name: "Grammar explanation" });
    expect(card).toHaveTextContent("Có yesterday nên dùng quá khứ.");
    expect(card).toHaveTextContent("I went there.");
    expect(card).toHaveTextContent("AI explanation, not yet checked");
  });

  it("shows an approved grammar lesson with its title and rules and no unchecked label", async () => {
    const socket = await live();
    act(() => socket.receive({ type: "grammar", explanation: "Dùng cho việc đã xong.", example: "I went there.",
      title: "Past simple", rules: ["Add -ed to regular verbs."], unverified: false }));
    const card = screen.getByRole("region", { name: "Grammar explanation" });
    expect(card).toHaveTextContent("Past simple");
    expect(card).toHaveTextContent("Add -ed to regular verbs.");
    expect(card).not.toHaveTextContent("AI explanation, not yet checked");
  });

  it("asks for more natural ways to say it and shows them with their explanations", async () => {
    const socket = await live();
    await userEvent.click(screen.getByRole("button", { name: "Sound natural" }));
    expect(socket.json()).toContainEqual({ type: "natural" });
    act(() => socket.receive({ type: "natural", items: [
      { sentence: "I went to the market yesterday.", explanation: "Cách nói thông thường." }] }));
    expect(screen.getByText("More natural ways to say it")).toBeInTheDocument();
    expect(screen.getByText("I went to the market yesterday.")).toBeInTheDocument();
  });

  it("lists the kinds of mistake in the summary by name, never a sentence", async () => {
    const socket = await live();
    act(() => socket.receive({ type: "ended", reason: "learner_ended", follow_ups: [],
      summary: { spoken_turns: 2, corrections: 2, hints: 0, suggestions: 0, words_to_reuse: [],
        error_types: ["verb_tense", "subject_verb_agreement"] } }));
    expect(screen.getByRole("region", { name: "Session summary" })).toHaveTextContent(
      "Grammar to review: verb tense, subject verb agreement");
  });
});

describe("grammar event parsing", () => {
  it("accepts a bounded explanation and drops malformed grammar and natural events", () => {
    const grammar = parseRealtimeEvent(JSON.stringify({ type: "grammar", explanation: "Quy tắc.", example: null, unverified: true }));
    expect(grammar?.type === "grammar" && grammar.grammar).toEqual({ explanation: "Quy tắc.", example: null, unverified: true });
    // A missing flag is never read as approved.
    const unflagged = parseRealtimeEvent(JSON.stringify({ type: "grammar", explanation: "Quy tắc.", example: null }));
    expect(unflagged?.type === "grammar" && unflagged.grammar.unverified).toBe(true);
    // The owner's approved lesson keeps its title and rules and may be longer than an AI explanation.
    const lesson = parseRealtimeEvent(JSON.stringify({ type: "grammar", explanation: "y".repeat(700), example: "I went.",
      title: "Past simple", rules: ["Use it for finished actions.", 3], unverified: false, point: "past_simple" }));
    expect(lesson?.type === "grammar" && lesson.grammar).toEqual({ explanation: "y".repeat(700), example: "I went.",
      title: "Past simple", rules: ["Use it for finished actions."], unverified: false });
    expect(parseRealtimeEvent(JSON.stringify({ type: "grammar", explanation: "" }))).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "grammar", explanation: "x".repeat(700) }))).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "natural", items: [] }))).toBeNull();
    const natural = parseRealtimeEvent(JSON.stringify({ type: "natural", items: [
      { sentence: "A.", explanation: "a" }, { sentence: "B.", explanation: "b" }, { sentence: "C.", explanation: "c" },
      { sentence: "D.", explanation: "d" }] }));
    expect(natural?.type === "natural" && natural.items).toHaveLength(3);
  });

  it("keeps only identifier-like error kinds in a summary", () => {
    const ended = parseRealtimeEvent(JSON.stringify({ type: "ended", reason: "x", follow_ups: [],
      summary: { spoken_turns: 1, corrections: 1, hints: 0, suggestions: 0, words_to_reuse: [],
        error_types: ["verb_tense", "He like football", 3, "ARTICLES"] } }));
    expect(ended?.type === "ended" && ended.summary?.error_types).toEqual(["verb_tense"]);
  });
});

describe("grammar notes in the summary (FR-8.1)", () => {
  const summary = { spoken_turns: 2, corrections: 1, hints: 0, suggestions: 0, words_to_reuse: [],
    error_types: ["verb_tense"], grammar_notes: [{ code: "verb_tense", note: "Chọn thì theo thời điểm.", example: "I went there." }] };

  it("keeps a bounded note with a short example and drops a malformed one", () => {
    const ended = (grammar_notes: unknown) => parseRealtimeEvent(JSON.stringify({ type: "ended", reason: "x",
      follow_ups: [], summary: { ...summary, grammar_notes } }));
    const good = ended(summary.grammar_notes);
    expect(good?.type === "ended" && good.summary?.grammar_notes).toEqual(summary.grammar_notes);
    const bad = ended([{ code: "Hà Nội", note: "x" }, { code: "articles", note: "" }, { code: "articles", note: "y".repeat(400) },
      { code: "articles", note: "ok", example: "z".repeat(300) }]);
    expect(bad?.type === "ended" && bad.summary?.grammar_notes).toEqual([{ code: "articles", note: "ok", example: null }]);
  });

  it("shows what to watch for with its example and says it is not yet reviewed", async () => {
    renderAt("/companion/realtime?entry=home");
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    const socket = FakeSocket.last!;
    act(() => {
      socket.open();
      socket.receive({ type: "ended", reason: "learner_ended", follow_ups: [], summary });
    });
    const card = screen.getByRole("region", { name: "Session summary" });
    expect(card).toHaveTextContent("verb tense");
    expect(card).toHaveTextContent("Chọn thì theo thời điểm.");
    expect(card).toHaveTextContent("I went there.");
    expect(card).toHaveTextContent("Short notes, not yet reviewed by an editor.");
  });
});


describe("RealtimeScreen microphone signal", () => {
  it("tells its host when the microphone is blocked and clears it on the next try", async () => {
    const pcm = await import("../../lib/audio/pcmRecorder");
    vi.mocked(pcm.startPcmRecorder).mockRejectedValueOnce(new pcm.MicrophoneError("denied"));
    const onMicError = vi.fn();
    const container = {
      config: { apiBaseUrl: "https://api.example.com" },
      gateway: { currentSession: vi.fn().mockResolvedValue({ userId: "u1", accessToken: "a.b.c" }) },
      plan: {}, companion: { getAgentConsent: vi.fn().mockResolvedValue(GRANTED) }, lists: { list: vi.fn().mockResolvedValue([]) },
    } as unknown as AppContainer;
    render(<QueryClientProvider client={new QueryClient()}><ContainerProvider container={container}>
      <MemoryRouter initialEntries={["/companion/realtime?entry=home"]}>
        <Routes><Route path="/companion/realtime" element={<RealtimeScreen onMicError={onMicError} />} /></Routes>
      </MemoryRouter></ContainerProvider></QueryClientProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(onMicError).toHaveBeenLastCalledWith(true));
    expect(await screen.findByText(/Allow microphone access/)).toBeVisible();
    await userEvent.click(await screen.findByRole("button", { name: "Start again" }));
    await vi.waitFor(() => expect(onMicError).toHaveBeenCalledWith(false));
  });
});
