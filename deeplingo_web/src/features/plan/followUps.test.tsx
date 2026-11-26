import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { CompanionApi } from "../companion/companionApi";
import { parseCompanionTurn } from "../companion/companionModels";
import { FollowUpList } from "./FollowUpList";
import { localDay, parsePlanItem } from "./planModels";

const ITEM = "11111111-1111-1111-1111-111111111111";
// Minimal backend CompanionTurnView, finished or not as each test needs.
const companionTurn = {
  session_ticket: "signed.ticket.value", expires_at: "2026-10-12T10:00:00Z", turn: 1, max_turns: 30,
  finished: false, language_code: "en", support_language_code: "vi", entry: "video", library_item_id: ITEM,
  topic: "Neil's difficult summer job", learner_transcript: "I like my job.", reply: "Nice!",
  reply_support: "Hay quá!", hints: { question: null, items: [], frame: null, model_sentence: null },
  correction: null, used_items: [], next: "continue", audio: null, audio_status: "unavailable",
};
const review = {
  id: "00000000-0000-0000-0000-000000000001", kind: "review", status: "open", minutes: 2,
  reason: "Sau cuộc trò chuyện, ôn 3 mục đã đến hạn.", item_count: 3, library_item_id: null, video_title: null,
  companion_entry: null,
};
const practice = {
  id: "00000000-0000-0000-0000-000000000002", kind: "video_practice", status: "open", minutes: 5,
  reason: "Luyện tiếp các từ của video vừa nói chuyện.", item_count: null, library_item_id: ITEM,
  video_title: "Neil's difficult summer job", companion_entry: null,
};

describe("follow-ups on a finished conversation", () => {
  it("parses follow-ups with the plan item rules and treats a missing field as none", () => {
    const finished = { ...companionTurn, finished: true, session_ticket: null, expires_at: null };
    expect(parseCompanionTurn(finished).follow_ups).toEqual([]);
    const turn = parseCompanionTurn({ ...finished, follow_ups: [review, practice] });
    expect(turn.follow_ups.map((item) => item.kind)).toEqual(["review", "video_practice"]);
    expect(() => parseCompanionTurn({ ...finished, follow_ups: [{ ...practice, library_item_id: null }] }))
      .toThrow(ApiError);
  });

  it("sends the learner's local day with turns and finish", async () => {
    const forms: FormData[] = [];
    const client = {
      postForm: vi.fn(async (_path: string, form: FormData) => {
        forms.push(form);
        return { ...companionTurn };
      }),
    };
    const api = new CompanionApi(client as never);
    await api.turn("ticket", new Int16Array(16));
    await api.finish("ticket");
    expect(forms.map((form) => form.get("day"))).toEqual([localDay(), localDay()]);
  });
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}</p>;
}

function mount(plan: object) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ContainerProvider container={{ plan } as unknown as AppContainer}>
        <MemoryRouter initialEntries={["/companion"]}>
          <Routes>
            <Route path="/companion" element={<FollowUpList items={[review, practice].map(parsePlanItem)} />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

describe("FollowUpList", () => {
  it("records the choice and opens the activity", async () => {
    const plan = { accept: vi.fn().mockResolvedValue(undefined), dismiss: vi.fn() };
    mount(plan);
    expect(screen.getByText("Suggested next steps")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Start" })[1]);
    expect(plan.accept).toHaveBeenCalledWith(practice.id);
    expect(await screen.findByTestId("where")).toHaveTextContent(`/library/videos/${ITEM}/watch`);
  });

  it("hides a dismissed follow-up", async () => {
    const plan = { accept: vi.fn(), dismiss: vi.fn().mockResolvedValue(undefined) };
    mount(plan);
    await userEvent.click(screen.getByRole("button", { name: "Not today: Review" }));
    expect(plan.dismiss).toHaveBeenCalledWith(review.id);
    await vi.waitFor(() => expect(screen.queryByText(review.reason)).not.toBeInTheDocument());
    expect(screen.getByText(practice.reason)).toBeInTheDocument();
  });
});
