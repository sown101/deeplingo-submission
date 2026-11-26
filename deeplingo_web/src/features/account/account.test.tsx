import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import type { LearnerLanguageProfile } from "../../lib/api/dto";
import { parseAgentMemory, parseAgentSignals, parseTranscriptPage, type AgentConsent, type AgentMemoryItem, type AgentSignal, type KeptTranscript, type TranscriptConsent } from "../companion/companionModels";
import { AccountScreen } from "./AccountScreen";

const signOut = vi.fn(async () => undefined);
vi.mock("../../app/AuthProvider", () => ({ useAuth: () => ({ signOut }) }));

function agentApi(consent: AgentConsent["status"] = "ask", signals: AgentSignal[] = []) {
  const state = { consent, signals: [...signals] };
  const view = () => ({ status: state.consent, decided_at: state.consent === "ask" ? null : "2026-10-29T10:00:00Z" });
  return {
    state,
    getAgentConsent: vi.fn(async () => view()),
    setAgentConsent: vi.fn(async (granted: boolean) => { state.consent = granted ? "granted" : "revoked"; return view(); }),
    getAgentSignals: vi.fn(async () => [...state.signals]),
    deleteAgentSignal: vi.fn(async (id: string) => { state.signals = state.signals.filter(item => item.id !== id); }),
    deleteAllAgentSignals: vi.fn(async () => { state.signals = []; }),
    ...transcriptApi(),
    ...memoryApi(),
  };
}

// What the agent remembers across conversations.
function memoryApi(notes: AgentMemoryItem[] = []) {
  const memory = { notes: [...notes] };
  return {
    memory,
    getAgentMemory: vi.fn(async () => [...memory.notes]),
    deleteAgentMemoryItem: vi.fn(async (id: string) => { memory.notes = memory.notes.filter(item => item.id !== id); }),
    deleteAllAgentMemory: vi.fn(async () => { memory.notes = []; }),
  };
}

const GOAL: AgentMemoryItem = { id: "m1", kind: "goal", text: "Order food in Beijing", language_code: "zh", created_at: "2026-11-14T10:00:00Z" };
const NEXT: AgentMemoryItem = { id: "m2", kind: "follow_up", text: "Practise the past tense", language_code: null, created_at: "2026-11-13T10:00:00Z" };

// FR-3.11: the separate transcript consent and the kept turns.
function transcriptApi(status: TranscriptConsent["status"] = "ask", turns: KeptTranscript[] = [], voice = true) {
  const kept = { status, turns: [...turns] };
  const view = (): TranscriptConsent => ({ status: kept.status, decided_at: kept.status === "ask" ? null : "2026-11-07T10:00:00Z",
    active: voice && kept.status === "granted" });
  return {
    kept,
    getTranscriptConsent: vi.fn(async () => view()),
    setTranscriptConsent: vi.fn(async (granted: boolean) => { kept.status = granted ? "granted" : "revoked"; return view(); }),
    getTranscripts: vi.fn(async (_before?: string | null) => ({ transcripts: [...kept.turns], next_before: null as string | null })),
    deleteTranscript: vi.fn(async (id: string) => { kept.turns = kept.turns.filter(item => item.id !== id); }),
    deleteAllTranscripts: vi.fn(async () => { kept.turns = []; }),
  };
}

const KEPT: KeptTranscript = {
  id: "33333333-3333-4333-8333-333333333333", session_id: "44444444-4444-4444-8444-444444444444", language_code: "en",
  topic: "Travel", assistance_level: 1, agent_text: "What did you do yesterday?", learner_text: "I go to the market yesterday.",
  recognized_text: "I go to the market yesterday",
  word_scores: [{ word: "market", accuracy: 41, error_type: "none" }, { word: "yesterday", accuracy: 95, error_type: "none" }],
  grammar_errors: [{ quote: "I go", suggestion: "I went", note: "Past tense.", error_type: "verb_tense" }],
  occurred_at: "2026-11-07T10:00:00Z",
};

const pick = (group: string, name: string) => userEvent.click(within(screen.getByRole("group", { name: group })).getByRole("button", { name }));
const chosen = (group: string) => within(screen.getByRole("group", { name: group })).getByRole("button", { pressed: true });
const openRow = async (name: string) => userEvent.click(await screen.findByRole("button", { name }));

const TRAVEL: AgentSignal = { id: "11111111-1111-4111-8111-111111111111", language_code: "en", kind: "topic", code: "travel", usage_count: 1 };
const TENSE: AgentSignal = { id: "22222222-2222-4222-8222-222222222222", language_code: "en", kind: "error_type", code: "verb_tense", usage_count: 3 };

function mount(failed = false, companion = agentApi(), client: unknown = { post: vi.fn(async () => undefined) }) {
  let profile: LearnerLanguageProfile = { learning_language: "en", support_language: "vi", is_complete: true, declared_level: "A2" };
  const saveProfile = vi.fn(async (selection: { learningLanguageCode: string; supportLanguageCode: string; declaredLevel?: string }) => {
    if (failed) throw Error("private provider detail");
    profile = { ...profile, learning_language: selection.learningLanguageCode, support_language: selection.supportLanguageCode,
      declared_level: selection.declaredLevel === undefined ? "HSK4" : selection.declaredLevel || null };
    return profile;
  });
  const onboarding = { loadProfile: async () => profile, saveProfile,
    loadLanguages: async () => [
      { code: "en", name_en: "English", is_active: true }, { code: "zh", name_en: "Chinese", is_active: true },
      { code: "vi", name_en: "Vietnamese", is_active: true },
    ] };
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  query.setQueryData(["my-words", "en"], { words: [] });
  render(<MemoryRouter initialEntries={["/account"]}><QueryClientProvider client={query}><ContainerProvider container={{ onboarding, companion, client } as unknown as AppContainer}>
    <Routes>
      <Route path="/account" element={<AccountScreen />} />
      <Route path="/signin" element={<p>Signed out</p>} />
    </Routes>
  </ContainerProvider></QueryClientProvider></MemoryRouter>);
  return { saveProfile, query, companion, client: client as { post: ReturnType<typeof vi.fn> } };
}

describe("Profile language settings", () => {
  it("saves the declared level through the language profile without a daily limit", async () => {
    const api = mount();
    await screen.findByRole("group", { name: "My level" });
    expect(chosen("My level")).toHaveTextContent("A2");
    expect(screen.queryByLabelText("New words per day")).not.toBeInTheDocument();
    await pick("My level", "B1");
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() => expect(api.saveProfile).toHaveBeenCalledWith({ learningLanguageCode: "en", supportLanguageCode: "vi", declaredLevel: "B1" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Profile saved.");
    expect(api.query.getQueryData(["language-profile"])).toMatchObject({ declared_level: "B1" });
    expect(api.query.getQueryState(["my-words", "en"])?.isInvalidated).toBe(true);
  });

  it("switches language and support, clears the previous scale, and submits the chosen HSK level", async () => {
    const api = mount();
    await screen.findByRole("group", { name: "Learning language" });
    await pick("Learning language", "Chinese");
    expect(chosen("My level")).toHaveTextContent("Not set");
    expect(within(screen.getByRole("group", { name: "My level" })).queryByRole("button", { name: "A2" })).not.toBeInTheDocument();
    await pick("My level", "HSK3");
    await pick("Support language", "English");
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() => expect(api.saveProfile).toHaveBeenCalledWith({ learningLanguageCode: "zh", supportLanguageCode: "en", declaredLevel: "HSK3" }));
  });

  it("preserves a different language's stored level when it was not edited", async () => {
    const api = mount();
    await screen.findByRole("group", { name: "Learning language" });
    await pick("Learning language", "Chinese");
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() => expect(api.saveProfile).toHaveBeenCalledWith({ learningLanguageCode: "zh", supportLanguageCode: "vi" }));
    await waitFor(() => expect(chosen("My level")).toHaveTextContent("HSK4"));
  });

  it("can clear a declared level and rejects equal learning and support languages", async () => {
    const api = mount();
    await screen.findByRole("group", { name: "My level" });
    await pick("My level", "Not set");
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() => expect(api.saveProfile).toHaveBeenCalledWith({ learningLanguageCode: "en", supportLanguageCode: "vi", declaredLevel: "" }));
    await pick("Support language", "English");
    expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled();
    expect(api.saveProfile).toHaveBeenCalledTimes(1);
  });

  it("reports a failed save without replacing the authoritative cached profile", async () => {
    const api = mount(true);
    await screen.findByRole("group", { name: "My level" });
    await pick("My level", "B1");
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByText("Your profile could not be saved. Please try again.")).toBeInTheDocument();
    expect(screen.queryByText("private provider detail")).not.toBeInTheDocument();
    expect(api.query.getQueryData(["language-profile"])).toMatchObject({ declared_level: "A2" });
  });
});

describe("Profile agent consent and personalization signals", () => {
  it("asks once, grants the single voice consent and can revoke it", async () => {
    const api = mount(false, agentApi("ask"));
    expect(await screen.findByText("You have not decided yet.")).toBeInTheDocument();
    const voice = screen.getByRole("switch", { name: "Voice processing" });
    expect(voice).toHaveAttribute("aria-checked", "false");
    await userEvent.click(voice);
    expect(await screen.findByText("Voice processing is on.")).toBeInTheDocument();
    expect(api.companion.setAgentConsent).toHaveBeenCalledWith(true);
    expect(screen.getByRole("switch", { name: "Voice processing" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("switch", { name: "Voice processing" }));
    expect(await screen.findByText("Voice processing is off.")).toBeInTheDocument();
    expect(api.companion.setAgentConsent).toHaveBeenLastCalledWith(false);
    // The full explanation stays one tap away.
    expect(screen.getAllByText(/sending audio to a speech service/)).toHaveLength(1);
  });

  it("lists signals as plain labels, deletes one, then all, and keeps them visible after revoking", async () => {
    const api = mount(false, agentApi("revoked", [TRAVEL, TENSE]));
    await waitFor(() => expect(screen.getByRole("button", { name: "What Tata knows about you" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "What Tata knows about you" })).toHaveAccessibleDescription("2 notes");
    await openRow("What Tata knows about you");
    expect(await screen.findByText("Travel")).toBeInTheDocument();
    expect(screen.getByText("Verb tense")).toBeInTheDocument();
    const signalsRow = screen.getByRole("button", { name: "What Tata knows about you" }).closest(".pf-row") as HTMLElement;
    expect(within(signalsRow).queryByText(/quote|transcript/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete signal: Travel" }));
    await waitFor(() => expect(screen.queryByText("Travel")).not.toBeInTheDocument());
    expect(api.companion.deleteAgentSignal).toHaveBeenCalledWith(TRAVEL.id);
    expect(screen.queryByRole("button", { name: "Delete everything the agent knows" })).not.toBeInTheDocument(); // it removes the labels only
    await userEvent.click(screen.getByRole("button", { name: "Delete all signals" }));
    expect(await screen.findByText("The agent has not noted anything about you yet.")).toBeInTheDocument();
    expect(api.companion.deleteAllAgentSignals).toHaveBeenCalledTimes(1);
  });

  it("shows a retryable error instead of an empty list when signals cannot load", async () => {
    const companion = agentApi("granted");
    companion.getAgentSignals.mockRejectedValueOnce(new Error("private provider detail"));
    mount(false, companion);
    const alert = await screen.findByText("Your agent settings could not be loaded.");
    expect(alert).toBeInTheDocument();
    expect(screen.queryByText("private provider detail")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What Tata knows about you" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Retry agent settings" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "What Tata knows about you" })).toBeEnabled());
    await openRow("What Tata knows about you");
    expect(await screen.findByText("The agent has not noted anything about you yet.")).toBeInTheDocument();
  });
});

describe("Profile kept transcripts (FR-3.11)", () => {
  it("is off until allowed, separate from voice, and can be stopped", async () => {
    const companion = { ...agentApi("granted"), ...transcriptApi("ask") };
    mount(false, companion);
    expect(await screen.findByText("Transcripts are off until you allow them.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Kept transcripts" })).toHaveAccessibleDescription("No transcripts are kept."));
    await userEvent.click(screen.getByRole("switch", { name: "Keep transcripts" }));
    expect(await screen.findByText("Transcripts are being kept.")).toBeInTheDocument();
    expect(companion.setTranscriptConsent).toHaveBeenCalledWith(true);
    expect(companion.setAgentConsent).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("switch", { name: "Keep transcripts" }));
    expect(await screen.findByText("Transcripts are not kept.")).toBeInTheDocument();
    expect(companion.setTranscriptConsent).toHaveBeenLastCalledWith(false);
  });

  it("says nothing is kept while voice processing is off even if transcripts are allowed", async () => {
    mount(false, { ...agentApi("revoked"), ...transcriptApi("granted", [], false) });
    expect(await screen.findByText("Transcripts are allowed but not kept while voice processing is off.")).toBeInTheDocument();
  });

  it("shows each kept turn with the agent's question, corrections and weak words, then deletes one and all", async () => {
    const second = { ...KEPT, id: "55555555-5555-4555-8555-555555555555", learner_text: "I like travel.", agent_text: null, grammar_errors: [], word_scores: [] };
    const companion = { ...agentApi("granted"), ...transcriptApi("revoked", [KEPT, second]) };
    mount(false, companion);
    await waitFor(() => expect(screen.getByRole("button", { name: "Kept transcripts" })).toHaveAccessibleDescription("2 turns kept"));
    await openRow("Kept transcripts");
    expect(await screen.findByText("I go to the market yesterday.")).toBeInTheDocument();
    expect(screen.getByText("What did you do yesterday?")).toBeInTheDocument();
    expect(screen.getByText("I went")).toBeInTheDocument();
    expect(screen.getByText("market")).toBeInTheDocument(); // accuracy under 60: worth practising
    const [first] = screen.getAllByRole("button", { name: /^Delete transcript from/ });
    await userEvent.click(first);
    await waitFor(() => expect(screen.queryByText("I go to the market yesterday.")).not.toBeInTheDocument());
    expect(companion.deleteTranscript).toHaveBeenCalledWith(KEPT.id);
    await userEvent.click(screen.getByRole("button", { name: "Delete all transcripts" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Kept transcripts" })).toHaveAccessibleDescription("No transcripts are kept."));
    expect(companion.deleteAllTranscripts).toHaveBeenCalledTimes(1);
  });

  it("loads older transcripts from the server cursor", async () => {
    const companion = { ...agentApi("granted"), ...transcriptApi("granted") };
    const older = { ...KEPT, id: "66666666-6666-4666-8666-666666666666", learner_text: "An older turn." };
    companion.getTranscripts
      .mockResolvedValueOnce({ transcripts: [KEPT], next_before: KEPT.occurred_at })
      .mockResolvedValueOnce({ transcripts: [older], next_before: null });
    mount(false, companion);
    await waitFor(() => expect(screen.getByRole("button", { name: "Kept transcripts" })).toBeEnabled());
    await openRow("Kept transcripts");
    await userEvent.click(await screen.findByRole("button", { name: "Show older transcripts" }));
    expect(await screen.findByText("An older turn.")).toBeInTheDocument();
    expect(companion.getTranscripts).toHaveBeenLastCalledWith(KEPT.occurred_at);
  });

  it("parses only the server contract", () => {
    const raw = { transcripts: [KEPT], next_before: null };
    expect(parseTranscriptPage(raw)).toEqual(raw);
    expect(() => parseTranscriptPage({ transcripts: [{ ...KEPT, id: "x" }], next_before: null })).toThrow();
    expect(() => parseTranscriptPage({ transcripts: [{ ...KEPT, word_scores: [{ word: "a", accuracy: "high", error_type: "none" }] }], next_before: null })).toThrow();
    expect(() => parseTranscriptPage({ transcripts: [{ ...KEPT, learner_text: "" }], next_before: null })).toThrow();
  });
});

describe("agent signal parsing", () => {
  it("rejects a kind or id the server contract does not allow", () => {
    const row = { id: TRAVEL.id, language_code: "en", kind: "topic", code: "travel", usage_count: 1 };
    expect(parseAgentSignals({ signals: [row] })).toEqual([row]);
    expect(() => parseAgentSignals({ signals: [{ ...row, kind: "quote" }] })).toThrow();
    expect(() => parseAgentSignals({ signals: [{ ...row, id: "not-a-uuid" }] })).toThrow();
  });
});

describe("delete my account (FR-6.1)", () => {
  beforeEach(() => signOut.mockClear());

  it("asks for a typed confirmation and deletes nothing until it is exact", async () => {
    const api = mount();
    await userEvent.click(await screen.findByRole("button", { name: "Delete my account" }));
    const confirm = screen.getByRole("button", { name: "Delete my account and data" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Type DELETE to confirm"), "delete");
    expect(confirm).toBeDisabled();
    await userEvent.clear(screen.getByLabelText("Type DELETE to confirm"));
    await userEvent.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    expect(confirm).toBeEnabled();
    expect(api.client.post).not.toHaveBeenCalled();
  });

  it("deletes through the server, signs out and leaves", async () => {
    const api = mount();
    await userEvent.click(await screen.findByRole("button", { name: "Delete my account" }));
    await userEvent.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: "Delete my account and data" }));
    expect(api.client.post).toHaveBeenCalledWith("/learner/me/account/delete", { confirm: "DELETE" });
    expect(await screen.findByText("Signed out")).toBeInTheDocument();
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("reports a failure without signing the learner out or claiming it is done", async () => {
    const api = mount(false, agentApi(), { post: vi.fn().mockRejectedValue(new Error("private detail")) });
    await userEvent.click(await screen.findByRole("button", { name: "Delete my account" }));
    await userEvent.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: "Delete my account and data" }));
    expect(await screen.findByText("Your account could not be deleted. Nothing was removed. Please try again.")).toBeInTheDocument();
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
    expect(signOut).not.toHaveBeenCalled();
    expect(api.client.post).toHaveBeenCalledTimes(1);
  });

  it("can be cancelled", async () => {
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Delete my account" }));
    const row = screen.getByRole("button", { name: "Delete my account" }).closest(".pf-row") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Type DELETE to confirm")).not.toBeInTheDocument();
  });
});


describe("Agent memory", () => {
  const ROW = "What Tata remembers about you";

  it("parses valid notes, an empty list, drops a malformed note and rejects a malformed response", () => {
    expect(parseAgentMemory({ items: [GOAL, NEXT] })).toEqual([GOAL, NEXT]);
    expect(parseAgentMemory({ items: [] })).toEqual([]);
    expect(parseAgentMemory({ items: [{ ...GOAL, kind: "secret" }, { ...NEXT, text: "" }, { ...GOAL, created_at: "soon" }, "x", NEXT] })).toEqual([NEXT]);
    expect(() => parseAgentMemory({ notes: [] })).toThrow();
    expect(() => parseAgentMemory({ items: "nope" })).toThrow();
    expect(() => parseAgentMemory(null)).toThrow();
  });

  it("shows the empty state", async () => {
    mount(false, { ...agentApi("granted"), ...memoryApi() });
    await waitFor(() => expect(screen.getByRole("button", { name: ROW })).toHaveAccessibleDescription("Tata has not noted anything yet"));
    await openRow(ROW);
    expect(screen.getByText("Tata has not noted anything yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete all" })).not.toBeInTheDocument();
  });

  it("shows loading, then each note with its kind label", async () => {
    const companion = { ...agentApi("granted"), ...memoryApi([GOAL, NEXT]) };
    companion.getAgentMemory.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve([GOAL, NEXT]), 400)));
    mount(false, companion);
    await openRow(ROW);
    expect(screen.getByText("Loading what Tata remembers…")).toBeInTheDocument();
    expect(await screen.findByText("Order food in Beijing")).toBeInTheDocument();
    expect(screen.getByText("Goal")).toBeInTheDocument();
    expect(screen.getByText("Next time")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete note: Practise the past tense" })).toBeInTheDocument();
  });

  it("shows an error and retries", async () => {
    const companion = { ...agentApi("granted"), ...memoryApi([GOAL]) };
    companion.getAgentMemory.mockRejectedValueOnce(new Error("private detail"));
    mount(false, companion);
    await openRow(ROW);
    expect(await screen.findByText("What Tata remembers could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry what Tata remembers" }));
    expect(await screen.findByText("Order food in Beijing")).toBeInTheDocument();
  });

  it("deletes one note by id and refreshes the list", async () => {
    const companion = { ...agentApi("granted"), ...memoryApi([GOAL, NEXT]) };
    mount(false, companion);
    await openRow(ROW);
    await userEvent.click(await screen.findByRole("button", { name: "Delete note: Order food in Beijing" }));
    await waitFor(() => expect(screen.queryByText("Order food in Beijing")).not.toBeInTheDocument());
    expect(companion.deleteAgentMemoryItem).toHaveBeenCalledWith("m1");
    expect(screen.getByText("Practise the past tense")).toBeInTheDocument();
    expect(companion.getAgentMemory.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("deletes all notes only after confirmation", async () => {
    const companion = { ...agentApi("granted"), ...memoryApi([GOAL, NEXT]) };
    mount(false, companion);
    await openRow(ROW);
    await userEvent.click(await screen.findByRole("button", { name: "Delete all" }));
    expect(companion.deleteAllAgentMemory).not.toHaveBeenCalled();
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete all" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, delete all" }));
    expect(await screen.findByText("Tata has not noted anything yet.")).toBeInTheDocument();
    expect(companion.deleteAllAgentMemory).toHaveBeenCalledTimes(1);
  });

  it("keeps the note and shows an error when a delete fails", async () => {
    const companion = { ...agentApi("granted"), ...memoryApi([GOAL]) };
    companion.deleteAgentMemoryItem.mockRejectedValueOnce(new Error("private detail"));
    mount(false, companion);
    await openRow(ROW);
    await userEvent.click(await screen.findByRole("button", { name: "Delete note: Order food in Beijing" }));
    expect(await screen.findByText("That change could not be saved. Please try again.")).toBeInTheDocument();
    expect(screen.getByText("Order food in Beijing")).toBeInTheDocument();
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
  });
});
