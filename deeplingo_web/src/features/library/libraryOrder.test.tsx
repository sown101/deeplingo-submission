import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { VideoLibrary } from "./VideoLibrary";

it("orders suitable videos near 95 percent first, then challenging, hard and unprofiled", async () => {
  const titles = ["Hard", "Unprofiled", "Very familiar", "Near 95", "Challenge"];
  const video = (title: string, index: number) => ({ library_item_id: String(index), video_id: String(index),
    title, thumbnail_url: null, duration_ms: 60000, source: "youtube", processing_status: "ready",
    learning_status: "ready", learning_object_count: 2, language_code: "en", failure: null,
    added_at: "2026-11-01T00:00:00Z" });
  const container = { library: { listVideos: vi.fn(async () => titles.map(video)) }, coverage: {
    forLibrary: vi.fn(async () => [
      { libraryItemId: "0", label: "hard", coverage: 0.7 },
      { libraryItemId: "2", label: "suitable", coverage: 0.99 },
      { libraryItemId: "3", label: "suitable", coverage: 0.951 },
      { libraryItemId: "4", label: "challenging", coverage: 0.91 },
    ]),
  } } as unknown as AppContainer;
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ContainerProvider container={container}><MemoryRouter><VideoLibrary /></MemoryRouter></ContainerProvider>
  </QueryClientProvider>);
  await waitFor(() => expect(screen.getAllByRole("heading", { level: 3 }).map(item => item.textContent))
    .toEqual(["Near 95", "Very familiar", "Challenge", "Hard", "Unprofiled"]));
});
