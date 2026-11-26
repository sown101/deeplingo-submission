import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { VideoLibrary } from "./VideoLibrary";
import type { LibraryApi } from "./libraryApi";
import type { LibraryVideoDetail, LearnerVideoImportResponse } from "../../lib/api/dto";
import { ContainerProvider } from "../../app/container";
import type { AppContainer } from "../../app/container";

function renderWithProviders(ui: React.ReactElement, container: Partial<AppContainer>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ContainerProvider container={container as AppContainer}>{ui}</ContainerProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const readyItem: LibraryVideoDetail = {
  library_item_id: "11111111-1111-1111-1111-111111111111",
  video_id: "22222222-2222-2222-2222-222222222222",
  title: "Me at the zoo",
  thumbnail_url: null,
  duration_ms: 19000,
  source: "youtube",
  processing_status: "ready",
  learning_status: "ready",
  learning_object_count: 10,
  learning_prepared_language_code: "vi",
  language_code: "en",
  added_at: "2026-09-24T10:00:00Z",
  failure: null,
  description: null,
  transcript_available: true,
};

function fakeLibraryApi(overrides: Partial<LibraryApi> = {}): LibraryApi {
  const api = {
    listVideos: vi.fn().mockResolvedValue([readyItem]),
    getVideo: vi.fn(),
    importVideo: vi.fn().mockResolvedValue({ command_status: "accepted", item: readyItem } satisfies LearnerVideoImportResponse),
    retryVideo: vi.fn().mockResolvedValue({ command_status: "retry_accepted", item: readyItem }),
    retryLearning: vi.fn(),
  };
  return Object.assign(api, overrides) as unknown as LibraryApi;
}

describe("Library", () => {
  it.each([false, true])("has only one import form, including when videos exist: %s", async (hasVideo) => {
    renderWithProviders(<VideoLibrary />, { library: fakeLibraryApi({ listVideos: vi.fn().mockResolvedValue(hasVideo ? [readyItem] : []) }) });
    await screen.findByText(hasVideo ? "Me at the zoo" : "Paste a YouTube link to start learning from it.");
    expect(screen.queryByRole("button", { name: "Add video" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add your first video" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Add" })).toHaveLength(1);
    expect(screen.getByLabelText("Paste a YouTube link")).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows ready items as a link straight into Watch", async () => {
    renderWithProviders(<VideoLibrary />, { library: fakeLibraryApi() });
    expect(await screen.findByText("Me at the zoo")).toBeInTheDocument();
    expect(screen.getByText("Ready for practice")).toBeInTheDocument();
    // On Home: h1 (greeting) -> h2 (Your videos) -> h3 (card).
    expect(screen.getByRole("heading", { name: "Your videos", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Me at the zoo", level: 3 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Me at the zoo" })).toHaveAttribute(
      "href",
      "/library/videos/11111111-1111-1111-1111-111111111111/watch",
    );
  });

  it("import submits only the learner-pasted URL", async () => {
    const library = fakeLibraryApi();
    renderWithProviders(<VideoLibrary />, { library });
    await screen.findByText("Me at the zoo");
    await userEvent.type(screen.getByLabelText("Paste a YouTube link"), "https://youtu.be/jNQXAC9IVRw{Enter}");
    await vi.waitFor(() => expect(library.importVideo).toHaveBeenCalled());
    expect(library.importVideo).toHaveBeenCalledWith("https://youtu.be/jNQXAC9IVRw");
    expect(library.importVideo).toHaveBeenCalledTimes(1);
  });

  it("blocks invalid input and duplicate submissions while an import is pending", async () => {
    let complete!: (value: LearnerVideoImportResponse) => void;
    const pending = new Promise<LearnerVideoImportResponse>(resolve => { complete = resolve; });
    const library = fakeLibraryApi({ importVideo: vi.fn().mockReturnValue(pending) });
    renderWithProviders(<VideoLibrary />, { library });
    await screen.findByText("Me at the zoo");
    const input = screen.getByLabelText("Paste a YouTube link");
    const submit = screen.getByRole("button", { name: "Add" });
    expect(submit).toBeDisabled();
    await userEvent.type(input, "not-a-url");
    expect(submit).toBeDisabled();
    expect(library.importVideo).not.toHaveBeenCalled();
    await userEvent.clear(input);
    await userEvent.type(input, "https://youtu.be/jNQXAC9IVRw{Enter}");
    await vi.waitFor(() => expect(input).toBeDisabled());
    expect(submit).toBeDisabled();
    fireEvent.submit(input.closest("form")!);
    expect(library.importVideo).toHaveBeenCalledTimes(1);
    await act(async () => { complete({ command_status: "accepted", item: readyItem }); });
    expect(input).toHaveValue("");
  });

  it("shows a safe API error in the same form and retains the URL for retry", async () => {
    const { ApiError } = await import("../../lib/api/errors");
    const library = fakeLibraryApi({ importVideo: vi.fn().mockRejectedValue(new ApiError("validation", 400, { code: "invalid_video_url", message: "private diagnostic" })) });
    renderWithProviders(<VideoLibrary />, { library });
    await screen.findByText("Me at the zoo");
    const input = screen.getByLabelText("Paste a YouTube link");
    await userEvent.type(input, "https://example.test/video{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("That link is not a valid YouTube URL.");
    expect(input).toHaveValue("https://example.test/video");
    expect(screen.queryByText("private diagnostic")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeEnabled();
  });

  it("offers Retry only when failure.retryable is true", async () => {
    const library = fakeLibraryApi({
      listVideos: vi.fn().mockResolvedValue([
        {
          ...readyItem,
          title: "Dead video",
          processing_status: "failed",
          learning_status: "not_started",
          failure: { code: "transcript_unavailable", retryable: false, message: "none" },
        },
        {
          ...readyItem,
          library_item_id: "99999999-9999-9999-9999-999999999999",
          title: "Retryable video",
          processing_status: "failed",
          learning_status: "not_started",
          failure: { code: "processing_failed", retryable: true, message: "boom" },
        },
      ]),
    });
    renderWithProviders(<VideoLibrary />, { library });
    expect(await screen.findByText("Dead video")).toBeInTheDocument();
    const retryButtons = screen.getAllByRole("button", { name: /^Retry$/ });
    expect(retryButtons).toHaveLength(1);
  });

  it("shows safe failure copy without raw diagnostics", async () => {
    const library = fakeLibraryApi({
      listVideos: vi.fn().mockResolvedValue([
        {
          ...readyItem,
          title: "Broken",
          processing_status: "failed",
          failure: { code: "video_unavailable", retryable: false, message: "HTTP 404 (internal trace abc)" },
        },
      ]),
    });
    renderWithProviders(<VideoLibrary />, { library });
    expect(await screen.findByText(/The video is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/internal trace/)).toBeNull();
  });
});

describe("Import limits", () => {
  it("explains the new-video budget and the request rate limit without echoing server text", async () => {
    const { importErrorMessage } = await import("./VideoLibrary");
    const { ApiError } = await import("../../lib/api/errors");
    const budget = importErrorMessage(new ApiError("unknown" as never, 429, { code: "new_video_budget_exhausted", message: "internal" }));
    expect(budget).toContain("limit for importing new videos");
    expect(budget).not.toContain("internal");
    expect(importErrorMessage(new ApiError("unknown" as never, 429, { code: "import_rate_limited", message: "x" })))
      .toContain("Too many import requests");
    expect(importErrorMessage(new ApiError("unknown" as never, 400, { code: "other", message: "x" })))
      .toContain("could not be imported");
  });
});

describe("coverage without a declared level (2026-11-06)", () => {
  it("points to Profile when the learner has not set a level", async () => {
    const onboarding = { loadProfile: vi.fn(async () => ({ learning_language: "en", support_language: "vi", is_complete: true, declared_level: null })) };
    renderWithProviders(<VideoLibrary />, { library: fakeLibraryApi(), onboarding: onboarding as never });
    expect(await screen.findByRole("link", { name: "Set your level in Profile to see how much of each video you may know." }))
      .toHaveAttribute("href", "/account#learning-preferences");
  });
});
