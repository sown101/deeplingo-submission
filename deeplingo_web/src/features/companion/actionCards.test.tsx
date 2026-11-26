import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { regionFromParam } from "../video/workspace/workspaceModels";
import { ActionCard, actionHref, HelpRequestButtons } from "./AgentLiveParts";
import { CompanionConversation } from "./CompanionConversation";
import { parseAgentAction, parseCompanionTurn, type AgentAction } from "./companionModels";
import { parseRealtimeEvent } from "./realtimeClient";
import { CompanionApi } from "./companionApi";
import { PlanApi } from "../plan/planApi";

const WORD_A = "11111111-1111-4111-8111-111111111111";
const WORD_B = "22222222-2222-4222-8222-222222222222";
const VIDEO = "33333333-3333-4333-8333-333333333333";
const SEG_A = "44444444-4444-4444-8444-444444444444";
const SEG_B = "55555555-5555-4555-8555-555555555555";
const ITEM = "66666666-6666-4666-8666-666666666666";
const REGION = `${SEG_A}_${SEG_B}`;

const review = { action: "open_review", language_code: "en", concept_ids: [WORD_A, WORD_B] };
const part = { action: "open_video_region", library_item_id: VIDEO, region_id: REGION, title: "Airport talk", start_ms: 1200 };
const edited = { action: "today_edited", change: "added", item_id: ITEM, kind: "review", minutes: 5, title: null };

describe("action cards are read strictly", () => {
  it("accepts the three shapes the server sends", () => {
    expect(parseAgentAction(review)).toEqual(review);
    expect(parseAgentAction(part)).toEqual(part);
    expect(parseAgentAction(edited)).toEqual(edited);
    // The voice event carries `type`, which is ignored.
    expect(parseRealtimeEvent(JSON.stringify({ type: "action", ...review }))).toEqual({ type: "action", card: review });
  });

  it("drops anything malformed or unknown instead of rendering it", () => {
    const broken = [
      null, "x", {}, { action: "delete_account" },
      { ...review, concept_ids: [] }, { ...review, concept_ids: ["not-an-id"] }, { ...review, language_code: "EN; drop" },
      { ...review, concept_ids: Array.from({ length: 21 }, () => WORD_A) },
      { ...part, region_id: "a_b" }, { ...part, library_item_id: "nope" }, { ...part, start_ms: -1 },
      { ...edited, change: "swapped" }, { ...edited, kind: "admin" }, { ...edited, minutes: 0 }, { ...edited, item_id: "x" },
    ];
    for (const value of broken) expect(parseAgentAction(value)).toBeNull();
    expect(parseRealtimeEvent(JSON.stringify({ type: "action", ...review, concept_ids: [] }))).toBeNull();
  });

  it("reads a turn's list of cards, keeps the good ones and never breaks the turn", () => {
    const base = turnFixture();
    expect(parseCompanionTurn(base).actions).toEqual([]);
    expect(parseCompanionTurn({ ...base, actions: [review, { action: "nope" }, edited] }).actions).toEqual([review, edited]);
    expect(parseCompanionTurn({ ...base, actions: "broken" }).actions).toEqual([]);
  });
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderWithApp(ui: React.ReactNode, container: object = {}) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ContainerProvider container={container as unknown as AppContainer}>
        <MemoryRouter initialEntries={["/agent"]}>
          <Routes>
            <Route path="/agent" element={<>{ui}<Where /></>} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

describe("ActionCard", () => {
  it("prepares a review of exactly the chosen words and goes there only on the button", async () => {
    renderWithApp(<ActionCard card={review as AgentAction} />);
    expect(screen.getByText("Words to review: 2")).toBeInTheDocument();
    const button = screen.getByRole("link", { name: "Start review" });
    expect(button).toHaveClass("dl-btn", "dl-btn--primary");
    expect(button).toHaveAttribute("href", `/review/en?types=choice&concepts=${WORD_A}%2C${WORD_B}&back=%2Fhome`);
    expect(screen.getByTestId("where")).toHaveTextContent("/agent");  // nothing navigated by itself
    await userEvent.click(button);
    expect(screen.getByTestId("where")).toHaveTextContent(`/review/en?types=choice&concepts=${WORD_A}%2C${WORD_B}`);
  });

  it("opens the learner's video at the part", async () => {
    renderWithApp(<ActionCard card={part as AgentAction} />);
    expect(screen.getByText("Airport talk")).toBeInTheDocument();
    const button = screen.getByRole("link", { name: "Open video part" });
    expect(button).toHaveClass("dl-btn", "dl-btn--primary");
    expect(button).toHaveAttribute("href", `/library/videos/${VIDEO}/watch?region=${REGION}`);
    expect(actionHref(part as Extract<AgentAction, { action: "open_video_region" }>)).toContain(`region=${REGION}`);
    // The watch page reads the same link back.
    expect(regionFromParam(REGION)).toEqual({ start_segment_id: SEG_A, end_segment_id: SEG_B });
    expect(regionFromParam("a_b")).toBeNull();
    expect(regionFromParam(null)).toBeNull();
  });

  it("says what changed in today's tasks and undoes exactly that change", async () => {
    const undoEdit = vi.fn().mockResolvedValue({});
    renderWithApp(<ActionCard card={edited as AgentAction} />, { plan: { undoEdit } });
    expect(screen.getByText("Added to today's tasks")).toBeInTheDocument();
    expect(screen.getByText("Review due words · 5 min")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(undoEdit).toHaveBeenCalledWith(ITEM, "added");
    expect(await screen.findByText("Undone")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("undoes a removal with the removed change", async () => {
    const undoEdit = vi.fn().mockResolvedValue({});
    renderWithApp(<ActionCard card={{ ...edited, change: "removed", kind: "my_words", title: "Neil's job" } as AgentAction} />,
      { plan: { undoEdit } });
    expect(screen.getByText("Removed from today's tasks")).toBeInTheDocument();
    expect(screen.getByText("Neil's job · 5 min")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(undoEdit).toHaveBeenCalledWith(ITEM, "removed");
  });

  it("shows an inline error and keeps the button when the undo fails, so the learner can try again", async () => {
    const undoEdit = vi.fn().mockRejectedValueOnce(new ApiError("conflict", 409, { code: "plan_item_decided" }))
      .mockResolvedValue({});
    renderWithApp(<ActionCard card={edited as AgentAction} />, { plan: { undoEdit } });
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That could not be undone");
    expect(screen.queryByText("Undone")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Undone")).toBeInTheDocument();
    expect(undoEdit).toHaveBeenCalledTimes(2);
  });
});

describe("HelpRequestButtons", () => {
  it("has the voice screen's four buttons and sends the matching request", async () => {
    const onRequest = vi.fn();
    renderWithApp(<HelpRequestButtons onRequest={onRequest} />);
    await userEvent.click(screen.getByRole("button", { name: "Hint" }));
    await userEvent.click(screen.getByRole("button", { name: "Ideas" }));
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    await userEvent.click(screen.getByRole("button", { name: "Sound natural" }));
    expect(onRequest.mock.calls.map(([request]) => request)).toEqual(["hint", "suggest", "explain", "natural"]);
  });
});

// --- The text conversation ------------------------------------------------------------------------------

function turnFixture(overrides: Record<string, unknown> = {}) {
  return {
    session_ticket: "signed.ticket.value", expires_at: "2026-10-12T10:00:00Z", turn: 0, max_turns: 20, finished: false,
    language_code: "en", support_language_code: "vi", entry: "home", library_item_id: null, topic: "Summer jobs",
    learner_transcript: null, reply: "Hello! What shall we do?", reply_support: "Xin chào! Mình làm gì nhé?",
    hints: { question: null, items: [], frame: null, model_sentence: null }, correction: null, used_items: [],
    next: "continue", audio: null, audio_status: "unavailable", ...overrides,
  };
}

function renderConversation(companion: object, container: object = {}) {
  renderWithApp(<CompanionConversation entry="home" item={null} onLeave={() => undefined} />, {
    companion: { getAgentConsent: vi.fn().mockResolvedValue({ status: "granted" }), ...companion }, ...container });
}

describe("the text conversation", () => {
  it("shows the agent's action cards on the turn, the same card as the voice screen", async () => {
    const start = vi.fn().mockResolvedValue(parseCompanionTurn(turnFixture({ actions: [review, edited] })));
    renderConversation({ start }, { plan: { undoEdit: vi.fn() } });
    expect(await screen.findByText("Hello! What shall we do?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start review" })).toHaveAttribute("href", expect.stringContaining("/review/en?"));
    expect(screen.getByText("Added to today's tasks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/agent");  // the conversation was not left
  });

  it("offers the four help buttons and sends each as a request, with or without the typed words", async () => {
    const user = userEvent.setup();
    const answer = parseCompanionTurn(turnFixture({ turn: 1, reply: "Here is a hint.", session_ticket: "next.ticket" }));
    const turnRequest = vi.fn().mockResolvedValue(answer);
    renderConversation({ start: vi.fn().mockResolvedValue(parseCompanionTurn(turnFixture())), turnRequest });
    await screen.findByText("Hello! What shall we do?");
    for (const name of ["Hint", "Ideas", "Explain", "Sound natural"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    await user.click(screen.getByRole("button", { name: "Hint" }));
    expect(turnRequest).toHaveBeenLastCalledWith("signed.ticket.value", "hint", undefined, expect.any(Function));
    expect(await screen.findByText("Here is a hint.")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Type your answer" }), "I like fly");
    await user.click(screen.getByRole("button", { name: "Sound natural" }));
    expect(turnRequest).toHaveBeenLastCalledWith("next.ticket", "natural", "I like fly", expect.any(Function));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Type your answer" })).toHaveValue(""));
    await user.click(screen.getByRole("button", { name: "Ideas" }));
    expect(turnRequest).toHaveBeenLastCalledWith("next.ticket", "suggest", undefined, expect.any(Function));
    await user.click(screen.getByRole("button", { name: "Explain" }));
    expect(turnRequest).toHaveBeenLastCalledWith("next.ticket", "explain", undefined, expect.any(Function));
  });

  it("says so when the help limit is reached and keeps the conversation open", async () => {
    const turnRequest = vi.fn().mockRejectedValue(new ApiError("conflict", 409, { code: "companion_help_limit" }));
    renderConversation({ start: vi.fn().mockResolvedValue(parseCompanionTurn(turnFixture())), turnRequest });
    await screen.findByText("Hello! What shall we do?");
    await userEvent.click(screen.getByRole("button", { name: "Hint" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That is enough help for this conversation.");
    expect(screen.getByRole("button", { name: "Hint" })).toBeInTheDocument();
  });
});

describe("the calls the cards make", () => {
  it("undoes a change with the item and which way it went, nothing else", async () => {
    const post = vi.fn().mockResolvedValue({ id: ITEM, kind: "review", status: "dismissed", minutes: 5, reason: "Bạn nhờ mình thêm.",
      item_count: 3, library_item_id: null, video_title: null, companion_entry: null });
    const item = await new PlanApi({ post } as never).undoEdit(ITEM, "added");
    expect(post).toHaveBeenCalledWith(`/learner/me/plan/items/${ITEM}/undo`, { change: "added" });
    expect(item.status).toBe("dismissed");
  });

  it("sends a help request as `request`, with the typed words only when there are some", async () => {
    const postForm = vi.fn().mockResolvedValue(turnFixture());
    const api = new CompanionApi({ postForm } as never);
    await api.turnRequest("t.k", "explain");
    await api.turnRequest("t.k", "natural", "I like fly");
    const [first, second] = postForm.mock.calls.map(([, form]) => form as FormData);
    expect(postForm.mock.calls[0][0]).toBe("/learner/me/companion/turns");
    expect([first.get("session_ticket"), first.get("request"), first.has("text")]).toEqual(["t.k", "explain", false]);
    expect([second.get("request"), second.get("text")]).toEqual(["natural", "I like fly"]);
  });
});
