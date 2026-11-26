import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { parsePlanItem, parseStudyPlan, planItemPath, type PlanItem } from "../plan/planModels";
import { HomeScreen } from "./HomeScreen";

const LIB = "11111111-1111-4111-8111-111111111111";
const item = (id: string, over: Partial<PlanItem> & Pick<PlanItem, "kind">): PlanItem => ({
  id, status: "open", minutes: 5, reason: "Lý do.", item_count: null, library_item_id: null, video_title: null,
  companion_entry: null, ...over,
});
const REVIEW = item("aaaaaaaa-0000-4000-8000-000000000001", { kind: "review", item_count: 7, minutes: 4,
  reason: "7 mục đã đến lúc ôn." });
const WATCH = item("aaaaaaaa-0000-4000-8000-000000000002", { kind: "video_practice", library_item_id: LIB,
  video_title: "Me at the zoo", reason: "Tiếp tục xem video “Me at the zoo” từ chỗ bạn đã dừng." });
const TOPIC = item("aaaaaaaa-0000-4000-8000-000000000003", { kind: "conversation", companion_entry: "home",
  reason: "Chọn một chủ đề rồi nói chuyện với mình." });
const ADD = item("aaaaaaaa-0000-4000-8000-000000000004", { kind: "add_video", minutes: 3, reason: "Thêm một video." });

function Where() {
  return <p data-testid="where">{useLocation().pathname + useLocation().search}</p>;
}

const PROGRESS = {
  language: null, languages: ["en"], streak: { current: 3, longest: 3, active_days: 3 },
  calendar: { days: [], active_days: 3, current_streak_days: 3 }, cards: [], accuracy: [], pronunciation: [],
  grammar: { learned: 0, done_correctly: 0 }, regions_completed: 0, speaking: { sessions: 0, minutes: 0 },
};

function mount({ items = [REVIEW, WATCH, TOPIC], plan, calendar, yesterday = null }: {
  items?: PlanItem[]; plan?: () => Promise<unknown>; calendar?: () => Promise<unknown>; yesterday?: unknown;
} = {}) {
  const planApi = {
    today: vi.fn(plan ?? (async () => ({ plan_id: "p1", day: "2026-10-29", language_code: "en", intro: "Chào bạn!", items, yesterday }))),
    accept: vi.fn(async (id: string) => ({ ...items.find((entry) => entry.id === id)!, status: "accepted" })),
    dismiss: vi.fn(async (id: string) => ({ ...items.find((entry) => entry.id === id)!, status: "dismissed" })),
  };
  const progress = {
    loadProgress: vi.fn(calendar ?? (async () => ({ ...PROGRESS }))),
  };
  const words = { list: vi.fn(async () => ({ words: [], summary: null })) };
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ContainerProvider container={{ plan: planApi, progress, words } as unknown as AppContainer}>
        <MemoryRouter initialEntries={["/home"]}>
          <Routes>
            <Route path="/home" element={<HomeScreen />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </ContainerProvider>
    </QueryClientProvider>,
  );
  return { planApi, progress };
}

describe("Home", () => {
  it("shows the video in progress and no list of suggestions", async () => {
    mount();
    await screen.findByText("Me at the zoo");
    expect(screen.queryByText("Suggested for you")).not.toBeInTheDocument();
    expect(screen.queryByText("Talk about a topic")).not.toBeInTheDocument();
    expect(screen.queryByText("Chào bạn!")).not.toBeInTheDocument();
  });

  it("opens the video only when the learner chooses it, recording the choice", async () => {
    const { planApi } = mount();
    await screen.findByText("Me at the zoo");
    expect(planApi.accept).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Resume this video" }));
    expect(planApi.accept).toHaveBeenCalledWith(WATCH.id);
    expect(await screen.findByTestId("where")).toHaveTextContent(`/library/videos/${LIB}/watch`);
  });

  it("still opens the video if the choice cannot be recorded", async () => {
    const { planApi } = mount();
    planApi.accept.mockRejectedValueOnce(new Error("down"));
    await userEvent.click(await screen.findByRole("button", { name: "Resume this video" }));
    expect(await screen.findByTestId("where")).toHaveTextContent(`/library/videos/${LIB}/watch`);
  });

  it("hides the video the learner puts off", async () => {
    const { planApi } = mount();
    await userEvent.click(await screen.findByRole("button", { name: "Not today" }));
    expect(planApi.dismiss).toHaveBeenCalledWith(WATCH.id);
    await waitFor(() => expect(screen.queryByText("Me at the zoo")).not.toBeInTheDocument());
  });

  it("offers a safe retry when the plan cannot load", async () => {
    const { planApi } = mount({ plan: async () => { throw new Error("private detail"); } });
    expect(await screen.findByText("Your suggestions could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
    planApi.today.mockResolvedValueOnce({ plan_id: "p1", day: "2026-10-29", language_code: "en", intro: "Chào lại!", items: [WATCH] });
    await userEvent.click(screen.getByRole("button", { name: "Retry suggestions" }));
    await screen.findByText("Me at the zoo");
  });

  it("keeps the video when the activity cannot load", async () => {
    mount({ calendar: async () => { throw new Error("down"); } });
    await screen.findByText("Me at the zoo");
  });
});

describe("plan models for Home", () => {
  it("opens a video suggestion on Watch, where the old practice page no longer exists", () => {
    expect(planItemPath(WATCH)).toBe(`/library/videos/${LIB}/watch`);
    expect(planItemPath(ADD)).toBe("/home");
    expect(planItemPath(TOPIC)).toBe("/agent?mode=voice&entry=home");
  });

  it("opens every conversation suggestion on the agent route, which is the only one that exists", () => {
    expect(planItemPath(item("aaaaaaaa-0000-4000-8000-000000000005", { kind: "conversation", companion_entry: "video",
      library_item_id: LIB }))).toBe(`/agent?mode=voice&entry=video&item=${LIB}`);
    expect(planItemPath(item("aaaaaaaa-0000-4000-8000-000000000006", { kind: "conversation", companion_entry: "review" })))
      .toBe("/agent?mode=voice&entry=review");
    expect(planItemPath(item("aaaaaaaa-0000-4000-8000-000000000007", { kind: "conversation" })))
      .toBe("/agent?mode=voice&entry=home");
  });

  it("reads yesterday's line and rejects malformed counts or long word lists", () => {
    const base = { plan_id: "p1", day: "2026-10-29", language_code: "en", intro: "Chào!", items: [] };
    const good = parseStudyPlan({ ...base, yesterday: { sessions: 2, minutes: 7, turns: 9, reuse_words: ["fly"] } });
    expect(good.yesterday).toEqual({ sessions: 2, minutes: 7, turns: 9, reuse_words: ["fly"] });
    expect(parseStudyPlan({ ...base, yesterday: null }).yesterday).toBeNull();
    expect(parseStudyPlan(base).yesterday).toBeNull();
    for (const bad of [{ sessions: -1, minutes: 1, turns: 0, reuse_words: [] }, { sessions: "2", minutes: 1, turns: 0, reuse_words: [] },
      { sessions: 1, minutes: 1, turns: 0, reuse_words: "fly" }]) {
      expect(() => parseStudyPlan({ ...base, yesterday: bad })).toThrow();
    }
    const trimmed = parseStudyPlan({ ...base, yesterday: { sessions: 1, minutes: 1, turns: 1, reuse_words: ["a", "", "b".repeat(90), 5, "c", "d", "e", "f", "g", "h"] } });
    expect(trimmed.yesterday?.reuse_words).toEqual(["a", "c", "d", "e", "f", "g"]);
  });

  it("parses a plan and rejects one with a malformed item", () => {
    const raw = { plan_id: "p1", day: "2026-10-29", language_code: "en", intro: "Chào!", items: [
      { ...REVIEW }, { ...TOPIC }] };
    expect(parseStudyPlan(raw).items.map((entry) => entry.kind)).toEqual(["review", "conversation"]);
    expect(() => parseStudyPlan({ ...raw, items: [{ ...REVIEW, kind: "surprise" }] })).toThrow();
    expect(() => parseStudyPlan({ ...raw, intro: "" })).toThrow();
    expect(parsePlanItem({ ...TOPIC }).companion_entry).toBe("home");
  });
});
