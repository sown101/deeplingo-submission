import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import type { LibraryVideoDetail } from "../../lib/api/dto";
import { VideoLibrary } from "../library/VideoLibrary";
import { CoverageBadge } from "./CoverageViews";
import { parseCoverageSummaries } from "./coverageModels";

const ITEM = "11111111-1111-1111-1111-111111111111";

function mount(ui: React.ReactNode, container: unknown) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ContainerProvider container={container as AppContainer}>{ui}</ContainerProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("coverage models", () => {
  it("parses a summary list, with null fields for a video not yet profiled", () => {
    const list = parseCoverageSummaries([
      { library_item_id: ITEM, language_code: "en", coverage: 0.97, label: "suitable", speech_rate_wpm: null, words_to_target: 0 },
      { library_item_id: "b", language_code: null, coverage: null, label: null, speech_rate_wpm: null, words_to_target: null },
    ]);
    expect(list[0]).toMatchObject({ label: "suitable", wordsToTarget: 0 });
    expect(list[1]).toMatchObject({ label: null, coverage: null });
  });

  it("rejects an unknown label or a negative share", () => {
    expect(() => parseCoverageSummaries([{ library_item_id: ITEM, label: "easy", coverage: 0.9 }])).toThrow(ApiError);
    expect(() => parseCoverageSummaries([{ library_item_id: ITEM, label: "hard", coverage: -0.1 }])).toThrow(ApiError);
    expect(() => parseCoverageSummaries({})).toThrow(ApiError);
  });
});

describe("coverage views", () => {
  it("the badge names the level of comfort and says it is an estimate", () => {
    mount(<CoverageBadge label="suitable" coverage={0.961} />, {});
    const badge = screen.getByText("Comfortable · about 96% known");
    expect(badge).toHaveAttribute("title", expect.stringContaining("estimate"));
  });

  it.each([
    ["suitable", 0.97, "Comfortable · about 97% known"],
    ["challenging", 0.94, "Challenging · about 94% known"],
    ["hard", 0.88, "Hard · about 88% known"],
  ])("keeps the %s Chinese label beside a visible calibration warning", async (label, coverage, badge) => {
    mount(<CoverageBadge label={label as "suitable" | "challenging" | "hard"} coverage={coverage as number} languageCode="zh" />, {});
    expect(screen.getByText(badge)).toBeInTheDocument();
    expect(screen.getByText("ước tính tiếng Trung chưa được hiệu chuẩn")).toBeVisible();
  });

  it("does not warn about Chinese calibration for an English video", () => {
    mount(<CoverageBadge label="challenging" coverage={0.94} languageCode="en" />, {});
    expect(screen.getByText("Challenging · about 94% known")).toBeInTheDocument();
    expect(screen.queryByText("ước tính tiếng Trung chưa được hiệu chuẩn")).not.toBeInTheDocument();
  });
});

describe("Library with coverage", () => {
  const item: LibraryVideoDetail = {
    library_item_id: ITEM, video_id: "22222222-2222-2222-2222-222222222222", title: "Me at the zoo", thumbnail_url: null,
    duration_ms: 19000, source: "youtube", processing_status: "ready", learning_status: "ready", learning_object_count: 10,
    learning_prepared_language_code: "vi", language_code: "en", added_at: "2026-09-24T10:00:00Z", failure: null,
    description: null, transcript_available: true,
  };

  it("marks a video with its coverage and leaves one without a profile unmarked", async () => {
    const other = { ...item, library_item_id: "33333333-3333-3333-3333-333333333333", title: "Cooking show" };
    const forLibrary = vi.fn(async () => parseCoverageSummaries([
      { library_item_id: ITEM, language_code: "en", coverage: 0.97, label: "suitable", speech_rate_wpm: 130, words_to_target: 0 },
      { library_item_id: other.library_item_id, language_code: null, coverage: null, label: null, speech_rate_wpm: null, words_to_target: null },
    ]));
    mount(<VideoLibrary />, { library: { listVideos: vi.fn(async () => [item, other]) }, coverage: { forLibrary } });
    expect(await screen.findByText("Comfortable · about 97% known")).toBeInTheDocument();
    expect(screen.getAllByText(/known$/)).toHaveLength(1);
  });

  it("looks the same when the estimate cannot be read", async () => {
    const forLibrary = vi.fn(async () => { throw new ApiError("server", 500, {}); });
    mount(<VideoLibrary />, { library: { listVideos: vi.fn(async () => [item]) }, coverage: { forLibrary } });
    expect(await screen.findByText("Me at the zoo")).toBeInTheDocument();
    await vi.waitFor(() => expect(forLibrary).toHaveBeenCalled());
    expect(screen.queryByText(/known$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("warns beside Chinese coverage in the Library using the estimate's language", async () => {
    const chinese = { ...item, library_item_id: "33333333-3333-3333-3333-333333333333", title: "Chinese video" };
    const forLibrary = vi.fn(async () => parseCoverageSummaries([
      { library_item_id: ITEM, language_code: "en", coverage: 0.97, label: "suitable", speech_rate_wpm: 130, words_to_target: 0 },
      { library_item_id: chinese.library_item_id, language_code: "zh", coverage: 0.88, label: "hard", speech_rate_wpm: 130, words_to_target: 10 },
    ]));
    mount(<VideoLibrary />, { library: { listVideos: vi.fn(async () => [item, chinese]) }, coverage: { forLibrary } });
    expect(await screen.findByText("Hard · about 88% known")).toBeInTheDocument();
    const chineseCard = screen.getByRole("heading", { name: "Chinese video" }).closest("li")!;
    expect(within(chineseCard).getByText("ước tính tiếng Trung chưa được hiệu chuẩn")).toBeVisible();
    const englishCard = screen.getByRole("heading", { name: "Me at the zoo" }).closest("li")!;
    expect(within(englishCard).getByText("Comfortable · about 97% known")).toBeInTheDocument();
    expect(within(englishCard).queryByText("ước tính tiếng Trung chưa được hiệu chuẩn")).not.toBeInTheDocument();
  });

  it("does not show a coverage warning when a Chinese video has no estimate", async () => {
    const chinese = { ...item, language_code: "zh" };
    const forLibrary = vi.fn(async () => parseCoverageSummaries([
      { library_item_id: ITEM, language_code: "zh", coverage: null, label: null, speech_rate_wpm: null, words_to_target: null },
    ]));
    mount(<VideoLibrary />, { library: { listVideos: vi.fn(async () => [chinese]) }, coverage: { forLibrary } });
    expect(await screen.findByText("Me at the zoo")).toBeInTheDocument();
    await vi.waitFor(() => expect(forLibrary).toHaveBeenCalled());
    expect(screen.queryByText(/known$/)).not.toBeInTheDocument();
    expect(screen.queryByText("ước tính tiếng Trung chưa được hiệu chuẩn")).not.toBeInTheDocument();
  });
});
