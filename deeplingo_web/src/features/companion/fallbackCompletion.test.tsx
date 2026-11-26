import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { CompanionConversation } from "./CompanionConversation";
import type { CompanionTurn } from "./companionModels";

const recorder = vi.hoisted(() => ({ stop: vi.fn(() => new Int16Array(16_000)), dispose: vi.fn() }));
vi.mock("../../lib/audio/pcmRecorder", async original => ({
  ...(await original<typeof import("../../lib/audio/pcmRecorder")>()),
  startPcmRecorder: vi.fn(async () => recorder),
}));

function turn(ticket: string, index: number): CompanionTurn {
  return { session_ticket: ticket, turn: index, max_turns: 30, finished: false,
    language_code: "en", support_language_code: "vi", entry: "home", library_item_id: null,
    topic: "Travel", learner_transcript: index ? "I travel every summer" : null,
    reply: "Tell me more.", reply_support: "Kể thêm nhé.",
    hints: { question: null, items: [], frame: null, model_sentence: null }, correction: null,
    used_items: [], next: "continue", audio: null, looked_up: [], follow_ups: [],
    practice_suggestion: null, weak_words: [], auto_hint_level: null, study_request: null, choices: [],
    grammar: null, natural: [], suggestions: [], actions: [] };
}

describe("ending recorded voice", () => {
  it("sends the current utterance before finishing with the newest ticket, then shows pronunciation", async () => {
    const companion = { getAgentConsent: vi.fn().mockResolvedValue({ status: "granted" }),
      start: vi.fn().mockResolvedValue(turn("opening", 0)),
      turn: vi.fn().mockResolvedValue(turn("after-turn", 1)),
      finish: vi.fn().mockResolvedValue({ weak_words: ["travel"] }) };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ContainerProvider container={{ companion } as unknown as AppContainer}>
      <MemoryRouter><CompanionConversation embedded entry="home" item={null} /></MemoryRouter>
    </ContainerProvider></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Start talking" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Start talking" }));
    await userEvent.click(await screen.findByRole("button", { name: "Tap to speak" }));
    await screen.findByRole("button", { name: /^Tap to send/ });
    await userEvent.click(screen.getByRole("button", { name: "End conversation" }));
    expect(await screen.findByText("Words to practise saying: travel")).toBeVisible();
    expect(companion.turn).toHaveBeenCalledWith("opening", expect.any(Int16Array), expect.any(Function));
    expect(companion.finish).toHaveBeenCalledTimes(1);
    expect(companion.finish).toHaveBeenCalledWith("after-turn");
    expect(recorder.dispose).toHaveBeenCalled();
  });
});
