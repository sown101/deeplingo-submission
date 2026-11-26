import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate, useSearchParams } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { CompanionConversation } from "./CompanionConversation";
import { parseCompanionTurn, type CompanionEntry } from "./companionModels";

const ITEM = "11111111-1111-1111-1111-111111111111";

// Mirrors backend CompanionTurnView.
export const companionTurn = {
  session_ticket: "signed.ticket.value",
  expires_at: "2026-10-12T10:00:00Z",
  turn: 0,
  max_turns: 20,
  finished: false,
  language_code: "en",
  support_language_code: "vi",
  entry: "video",
  library_item_id: ITEM,
  topic: "Neil's difficult summer job",
  learner_transcript: null,
  reply: "Have you ever had a difficult job?",
  reply_support: "Bạn đã bao giờ có một công việc khó khăn chưa?",
  hints: {
    question: "Bạn có thể kể về một công việc khó.",
    items: [{ id: "c1", text: "difficult", meaning: "khó khăn" }],
    frame: { frame: "Yes, I had a ___ job.", reason: "Dùng 'had' cho việc đã qua." },
    model_sentence: "Yes, I had a difficult job.",
  },
  correction: null,
  used_items: [],
  next: "continue",
  audio: { mime_type: "audio/mpeg", base64: "SUQz" },
  audio_status: "ready",
};

const lookedUpFarm = {
  word: "farm",
  headword: "farm",
  senses: [{ text: "A place where crops are grown or animals are raised.", part_of_speech: "noun" }],
  source_name: "Wiktionary",
  source_license: "CC BY-SA 4.0",
  source_url: "https://en.wiktionary.org/wiki/farm",
};

describe("companion turn parsing", () => {
  it("accepts the backend shape", () => {
    const turn = parseCompanionTurn(companionTurn);
    expect(turn.hints.items[0].text).toBe("difficult");
    expect(turn.audio?.mime_type).toBe("audio/mpeg");
  });

  it("accepts looked-up dictionary words and treats a missing field as none", () => {
    expect(parseCompanionTurn(companionTurn).looked_up).toEqual([]);
    const turn = parseCompanionTurn({ ...companionTurn, looked_up: [lookedUpFarm] });
    expect(turn.looked_up[0].senses[0].part_of_speech).toBe("noun");
    for (const broken of [
      { ...lookedUpFarm, senses: [] },
      { ...lookedUpFarm, source_url: "javascript:alert(1)" },
      { ...lookedUpFarm, headword: " " },
    ]) {
      expect(() => parseCompanionTurn({ ...companionTurn, looked_up: [broken] })).toThrow(ApiError);
    }
  });

  it("accepts a finished turn without ticket and a text-only turn", () => {
    const finished = parseCompanionTurn({ ...companionTurn, finished: true, session_ticket: null, expires_at: null,
      audio: null, audio_status: "unavailable" });
    expect(finished.finished).toBe(true);
    expect(finished.audio).toBeNull();
  });

  it("accepts a practice suggestion and treats a missing one as none (M1 S3)", () => {
    expect(parseCompanionTurn(companionTurn).practice_suggestion).toBeNull();
    const suggestion = { tool: "dictation", segment_id: ITEM, start_ms: 8000, end_ms: 12000, reason: "Nghe lại câu này." };
    expect(parseCompanionTurn({ ...companionTurn, practice_suggestion: suggestion }).practice_suggestion).toEqual(suggestion);
    for (const broken of [
      { ...suggestion, tool: "questions" },
      { ...suggestion, segment_id: "s2" },
      { ...suggestion, end_ms: 8000 },
      { ...suggestion, reason: " " },
    ]) {
      expect(() => parseCompanionTurn({ ...companionTurn, practice_suggestion: broken })).toThrow(ApiError);
    }
  });

  it("rejects inconsistent or unsafe shapes", () => {
    for (const broken of [
      { ...companionTurn, finished: true },
      { ...companionTurn, session_ticket: null },
      { ...companionTurn, audio: null },
      { ...companionTurn, audio_status: "unavailable" },
      { ...companionTurn, audio: { mime_type: "text/html", base64: "SUQz" } },
      { ...companionTurn, audio: { mime_type: "audio/mpeg", base64: "<script>" } },
      { ...companionTurn, entry: "anywhere" },
      { ...companionTurn, next: "grade" },
      { ...companionTurn, turn: 21 },
      { ...companionTurn, library_item_id: "not-a-uuid" },
      { ...companionTurn, reply: " " },
      { ...companionTurn, hints: { ...companionTurn.hints, items: [{ id: "c1" }] } },
    ]) {
      expect(() => parseCompanionTurn(broken)).toThrow(ApiError);
    }
  });
});

// The text channel as the agent screen shows it when live voice or the microphone is unavailable.
function Conversation() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  return <CompanionConversation entry={(params.get("entry") ?? "home") as CompanionEntry} item={params.get("item")}
    onLeave={() => navigate("/home")} />;
}

function renderAt(path: string, companion: object, client: object = {}) {
  const container = { client, companion: { getAgentConsent: vi.fn().mockResolvedValue({ status: "granted" }), ...companion } } as unknown as AppContainer;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ContainerProvider container={container}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/companion" element={<Conversation />} />
            <Route path="/home" element={<p>Home screen</p>} />
          </Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

describe("the text conversation", () => {
  it("starts a video conversation with only the entry and selected item", async () => {
    const start = vi.fn().mockResolvedValue(parseCompanionTurn(companionTurn));
    renderAt(`/companion?entry=video&item=${ITEM}`, { start, turn: vi.fn() });
    expect(await screen.findByText("Have you ever had a difficult job?")).toBeInTheDocument();
    expect(start).toHaveBeenCalledWith("video", ITEM);
    expect(screen.getByText("Turn 0 of 20")).toBeInTheDocument();
    expect(screen.getByText(/Saved words you use correctly can update/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tap to speak" })).toBeInTheDocument();
    // The voice link goes to the agent screen (there is no /companion/realtime route) in voice mode.
    expect(screen.getByRole("link", { name: "Reflex practice (trial)" }))
      .toHaveAttribute("href", `/agent?mode=voice&entry=video&item=${ITEM}`);
  });

  it("shows a looked-up word with its dictionary source", async () => {
    const start = vi.fn().mockResolvedValue(parseCompanionTurn({ ...companionTurn, looked_up: [lookedUpFarm] }));
    renderAt(`/companion?entry=video&item=${ITEM}`, { start, turn: vi.fn() });
    expect(await screen.findByLabelText("Dictionary: farm")).toBeInTheDocument();
    expect(screen.getByText("A place where crops are grown or animals are raised.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Wiktionary" })).toHaveAttribute("href", "https://en.wiktionary.org/wiki/farm");
    expect(screen.getByText(/CC BY-SA 4.0/)).toBeInTheDocument();
  });

  it("shows the Vietnamese line on request and opens hints one level at a time", async () => {
    const user = userEvent.setup();
    renderAt("/companion?entry=home", { start: vi.fn().mockResolvedValue(parseCompanionTurn(companionTurn)),
      turn: vi.fn() });
    await screen.findByText("Have you ever had a difficult job?");
    expect(screen.queryByText(companionTurn.reply_support)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Vietnamese" }));
    expect(screen.getByText(companionTurn.reply_support)).toBeInTheDocument();

    expect(screen.queryByText("Bạn có thể kể về một công việc khó.")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Need a hint?" }));
    expect(screen.getByText("Bạn có thể kể về một công việc khó.")).toBeInTheDocument();
    expect(screen.queryByText("difficult")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Another hint" }));
    expect(screen.getByText("difficult")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Another hint" }));
    expect(screen.getByText("Yes, I had a ___ job.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Another hint" }));
    expect(screen.getByText("Yes, I had a difficult job.")).toBeInTheDocument();
    expect(screen.getByText("Now say it in your own words.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Another hint" })).toBeNull();
  });

  it("offers the opening choices when no topic was chosen and sends the tapped one as the learner's answer", async () => {
    const user = userEvent.setup();
    const opening = parseCompanionTurn({ ...companionTurn, reply: "Hi! What would you like to do today?",
      choices: [{ id: "words", count: 3 }, { id: "free" }] });
    const reply = parseCompanionTurn({ ...companionTurn, turn: 1, reply: "Let's start.", session_ticket: "next.ticket.value" });
    const turnText = vi.fn().mockResolvedValue(reply);
    renderAt("/companion?entry=home", { start: vi.fn().mockResolvedValue(opening), turn: vi.fn(), turnText,
      finish: vi.fn().mockResolvedValue(undefined) });
    await screen.findByText("Hi! What would you like to do today?");
    await user.click(screen.getByRole("button", { name: "Practise 3 words due today" }));
    expect(turnText).toHaveBeenCalledWith("signed.ticket.value", "Practise 3 words due today", expect.any(Function));
    expect(await screen.findByText("Let's start.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Chat about a topic I choose" })).toBeNull();
  });

  it("explains why a conversation cannot start and offers a new one", async () => {
    const start = vi.fn().mockRejectedValue(new ApiError("conflict", 409, { code: "companion_no_items" }));
    renderAt("/companion?entry=review", { start, turn: vi.fn() });
    expect(await screen.findByRole("alert")).toHaveTextContent("Watch and prepare a video first");
    expect(screen.getByRole("button", { name: "Start a new conversation" })).toBeInTheDocument();
  });

  it("offers text chat without voice consent and sends only typed replies", async () => {
    const user = userEvent.setup();
    const start = vi.fn().mockResolvedValue(parseCompanionTurn(companionTurn));
    const setAgentConsent = vi.fn();
    const turnText = vi.fn().mockResolvedValue(parseCompanionTurn({
      ...companionTurn, turn: 1, reply: "Nice to meet you.", session_ticket: "next.ticket.value",
    }));
    renderAt("/companion?entry=home", {
      getAgentConsent: vi.fn().mockResolvedValue({ status: "revoked" }), setAgentConsent, start, turnText,
      finish: vi.fn().mockResolvedValue(undefined),
    });

    const button = await screen.findByRole("button", { name: "Start text chat" });
    expect(screen.getByText(/AI processes what you type/)).toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
    await user.click(button);
    expect(start).toHaveBeenCalledWith("home", null, { text_only: true });
    const input = await screen.findByRole("textbox", { name: "Type your answer" });
    await user.type(input, "Hello Tata");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Nice to meet you.")).toBeInTheDocument();
    expect(turnText).toHaveBeenCalledWith("signed.ticket.value", "Hello Tata", undefined);
    expect(screen.queryByRole("button", { name: "Tap to speak" })).not.toBeInTheDocument();
    expect(setAgentConsent).not.toHaveBeenCalled();
  });

  it("takes a typed answer when the microphone is unavailable", async () => {
    const user = userEvent.setup();
    const reply = parseCompanionTurn({ ...companionTurn, turn: 1, learner_transcript: "I had a job at a farm",
      reply: "A farm! Was it hard?", session_ticket: "next.ticket.value" });
    const turnText = vi.fn().mockResolvedValue(reply);
    renderAt("/companion?entry=home", { start: vi.fn().mockResolvedValue(parseCompanionTurn(companionTurn)),
      turn: vi.fn(), turnText, finish: vi.fn().mockResolvedValue(undefined) });
    await screen.findByText("Have you ever had a difficult job?");
    await user.type(screen.getByRole("textbox", { name: "Type your answer" }), "I had a job at a farm");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(turnText).toHaveBeenCalledWith("signed.ticket.value", "I had a job at a farm", expect.any(Function));
    expect(await screen.findByText("A farm! Was it hard?")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Type your answer" })).toHaveValue("");
  });

  it("opens the hints without a tap when the learner hesitated, and shows practice added to the notebook", async () => {
    const user = userEvent.setup();
    const hesitated = parseCompanionTurn({ ...companionTurn, turn: 1, learner_transcript: "um... uh",
      session_ticket: "next.ticket.value", auto_hint_level: 1,
      study_request: { kind: "grammar_redo", item: "en.a1.past_simple", title: "Past simple" } });
    renderAt("/companion?entry=home", { start: vi.fn().mockResolvedValue(parseCompanionTurn(companionTurn)),
      turn: vi.fn(), turnText: vi.fn().mockResolvedValue(hesitated), finish: vi.fn().mockResolvedValue(undefined) });
    await screen.findByText("Have you ever had a difficult job?");
    await user.type(screen.getByRole("textbox", { name: "Type your answer" }), "um... uh");
    await user.click(screen.getByRole("button", { name: "Send" }));
    // Step 1 of the server's ladder: the guiding question and the words, without pressing "Need a hint?".
    expect(await screen.findByText("Bạn có thể kể về một công việc khó.")).toBeInTheDocument();
    expect(screen.getByText("difficult")).toBeInTheDocument();
    expect(screen.queryByText("Yes, I had a ___ job.")).toBeNull();
    expect(screen.getByText("Tata will remind you to practise this")).toBeInTheDocument();
    expect(screen.getByText("Past simple")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Do the grammar exercise" })).toHaveAttribute("href", "/words/lists?tab=grammar");
  });

  it("parses the hint step and the notebook notice strictly", () => {
    expect(parseCompanionTurn(companionTurn).auto_hint_level).toBeNull();
    expect(parseCompanionTurn(companionTurn).study_request).toBeNull();
    expect(() => parseCompanionTurn({ ...companionTurn, auto_hint_level: 4 })).toThrow(ApiError);
    expect(() => parseCompanionTurn({ ...companionTurn, study_request: { kind: "delete", item: "x" } })).toThrow(ApiError);
  });
});

const emptyHints = { question: null, items: [], frame: null, model_sentence: null };
const grammarHelp = { title: "Past simple", explanation: "Use the past form for finished events.", example: "I worked on a farm.",
  rules: ["Add -ed to regular verbs."], unverified: true };
const naturalHelp = [{ sentence: "I worked on a farm.", explanation: "Past form of work." }];
const ideasHelp = [{ sentence: "It was hard but fun.", explanation: "Say how it felt." }];

describe("help the agent gives without a tap: parsing", () => {
  it("accepts grammar, natural ways and ideas, and treats missing ones as none", () => {
    const none = parseCompanionTurn(companionTurn);
    expect([none.grammar, none.natural, none.suggestions]).toEqual([null, [], []]);
    const turn = parseCompanionTurn({ ...companionTurn, grammar: grammarHelp, natural: naturalHelp, suggestions: ideasHelp });
    expect(turn.grammar).toEqual(grammarHelp);
    expect(turn.natural).toEqual(naturalHelp);
    expect(turn.suggestions).toEqual(ideasHelp);
    expect(parseCompanionTurn({ ...companionTurn, grammar: { explanation: "Short rule." } }).grammar)
      .toEqual({ title: null, explanation: "Short rule.", example: null, rules: [], unverified: false });
  });

  it("drops malformed optional help without breaking the turn", () => {
    const turn = parseCompanionTurn({ ...companionTurn, grammar: { explanation: " " },
      natural: [{ sentence: "Fine", explanation: "ok" }, { sentence: 3 }], suggestions: "none" });
    expect(turn.reply).toBe(companionTurn.reply);
    expect([turn.grammar, turn.natural, turn.suggestions]).toEqual([null, [], []]);
    expect(parseCompanionTurn({ ...companionTurn, grammar: { ...grammarHelp, unverified: "yes" } }).grammar).toBeNull();
  });
});

describe("help the agent gives without a tap: the text conversation", () => {
  async function startWith(extra: object) {
    renderAt("/companion?entry=home", { start: vi.fn().mockResolvedValue(parseCompanionTurn({ ...companionTurn, ...extra })),
      turn: vi.fn() });
    await screen.findByText("Have you ever had a difficult job?");
  }

  it("shows a grammar explanation on the turn it came with, marked when unverified", async () => {
    await startWith({ grammar: grammarHelp });
    const card = screen.getByLabelText("Grammar explanation");
    expect(card).toHaveTextContent("Past simple");
    expect(card).toHaveTextContent("Use the past form for finished events.");
    expect(card).toHaveTextContent("I worked on a farm.");
    expect(card).toHaveTextContent("Add -ed to regular verbs.");
    expect(card).toHaveTextContent("AI explanation, not yet checked.");
  });

  it("does not mark an approved grammar explanation as unchecked", async () => {
    await startWith({ grammar: { ...grammarHelp, unverified: false } });
    expect(screen.getByLabelText("Grammar explanation")).not.toHaveTextContent("not yet checked");
  });

  it("shows more natural ways and ideas for what to say", async () => {
    await startWith({ natural: naturalHelp, suggestions: ideasHelp });
    expect(screen.getByText("More natural ways to say it")).toBeInTheDocument();
    expect(screen.getByText("Past form of work.")).toBeInTheDocument();
    expect(screen.getByText("Things you could say")).toBeInTheDocument();
    expect(screen.getByText("It was hard but fun.")).toBeInTheDocument();
  });

  it("shows no help cards when the agent gave none", async () => {
    await startWith({});
    expect(screen.queryByLabelText("Grammar explanation")).toBeNull();
    expect(screen.queryByText("More natural ways to say it")).toBeNull();
    expect(screen.queryByText("Things you could say")).toBeNull();
  });

  it("keeps the correction visible next to the help", async () => {
    await startWith({ correction: { quote: "I work", suggestion: "I worked", note: "Past." }, grammar: grammarHelp });
    expect(screen.getByText("I worked")).toBeInTheDocument();
    expect(screen.getByLabelText("Grammar explanation")).toBeInTheDocument();
  });

  it("offers no hint control when the turn carries no hint", async () => {
    await startWith({ hints: emptyHints });
    expect(screen.queryByRole("button", { name: "Need a hint?" })).toBeNull();
    expect(screen.queryByLabelText("Hints")).toBeNull();
  });

  it("does not offer hint steps the agent left empty", async () => {
    const user = userEvent.setup();
    await startWith({ hints: { ...emptyHints, question: "Kể về một công việc." } });
    await user.click(screen.getByRole("button", { name: "Need a hint?" }));
    expect(screen.getByText("Kể về một công việc.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Another hint" })).toBeNull();
  });

  it("does not carry a hint over to the next turn that has none", async () => {
    const user = userEvent.setup();
    const next = parseCompanionTurn({ ...companionTurn, turn: 1, reply: "Tell me more.", hints: emptyHints,
      session_ticket: "next.ticket.value" });
    renderAt("/companion?entry=home", { start: vi.fn().mockResolvedValue(parseCompanionTurn(companionTurn)),
      turn: vi.fn(), turnText: vi.fn().mockResolvedValue(next), finish: vi.fn().mockResolvedValue(undefined) });
    await screen.findByText("Have you ever had a difficult job?");
    await user.click(screen.getByRole("button", { name: "Need a hint?" }));
    expect(screen.getByText("Bạn có thể kể về một công việc khó.")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Type your answer" }), "I had one");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Tell me more.");
    expect(screen.queryByText("Bạn có thể kể về một công việc khó.")).toBeNull();
    expect(screen.queryByRole("button", { name: "Need a hint?" })).toBeNull();
  });
});

describe("leaving a conversation", () => {
  it("shows final pronunciation and server-confirmed word use without deciding correctness locally", async () => {
    const sessionId = "11111111-1111-4111-8111-111111111111";
    const conceptId = "22222222-2222-4222-8222-222222222222";
    const get = vi.fn().mockResolvedValue({ session_id: sessionId, status: "completed",
      events: [{ concept_id: conceptId, text: "reservation", kind: "framed_use" }] });
    renderAt("/companion?entry=home", { start: vi.fn().mockResolvedValue(parseCompanionTurn({ ...companionTurn,
      finished: true, session_ticket: null, expires_at: null, weak_words: ["reservation"],
      analysis: { session_id: sessionId, status: "queued" } })) }, { get });
    expect(await screen.findByText("Words to practise saying: reservation")).toBeVisible();
    expect(await screen.findByText(/Used with support/)).toBeVisible();
    expect(get).toHaveBeenCalledWith(`/learner/me/speaking-sessions/${sessionId}`);
  });

  it("leaving before speaking does not finish a session on the server", async () => {
    const user = userEvent.setup();
    const finish = vi.fn().mockResolvedValue(undefined);
    renderAt("/companion?entry=home", {
      start: vi.fn().mockResolvedValue(parseCompanionTurn(companionTurn)), turn: vi.fn(), finish,
    });
    await screen.findByText("Have you ever had a difficult job?");
    await user.click(screen.getByRole("button", { name: "Leave" }));
    expect(await screen.findByText("Home screen")).toBeInTheDocument();
    expect(finish).not.toHaveBeenCalled();
  });
});
