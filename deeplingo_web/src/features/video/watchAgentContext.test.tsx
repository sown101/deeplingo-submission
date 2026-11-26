import { useEffect, useState } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { AppShell } from "../../app/AppShell";
import { WatchScreen } from "./WatchScreen";

vi.mock("../../app/AuthProvider", () => ({ useAuth: () => ({ signOut: vi.fn() }) }));
const lifecycle = vi.hoisted(() => ({ mounted: vi.fn(), closed: vi.fn() }));
vi.mock("./VideoAgentPanel", () => ({ VideoAgentPanel: () => {
  const [turns, setTurns] = useState(0);
  useEffect(() => { lifecycle.mounted(); return lifecycle.closed; }, []);
  return <button onClick={() => setTurns(value => value + 1)}>Synthetic turn {turns}</button>;
} }));

it("opening the first AI part does not remount an already open Tata conversation", async () => {
  vi.stubGlobal("scrollTo", vi.fn());
  lifecycle.mounted.mockClear(); lifecycle.closed.mockClear();
  const video = "33333333-3333-4333-8333-333333333333";
  const sentence = "44444444-4444-4444-8444-444444444444";
  let resolveParts!: (parts: unknown) => void;
  const pending = new Promise(resolve => { resolveParts = resolve; });
  const region = { start_segment_id: sentence, end_segment_id: sentence, start_ms: 0, end_ms: 5000,
    segment_count: 1, preparation: null };
  const playback = {
    getPlayableVideo: vi.fn().mockResolvedValue({ library_item_id: video, video_id: video, provider: "youtube",
      external_video_id: "jNQXAC9IVRw", title: "Synthetic video", language_code: "en", duration_ms: 5000 }),
    getTranscript: vi.fn().mockResolvedValue({ library_item_id: video, language_code: "en", translation_language_code: null,
      segments: [{ segment_id: sentence, sequence: 1, text: "Synthetic sentence.", start_ms: 0, end_ms: 5000,
        translation: null, romanizations: [], learning_objects: [] }] }),
    getWorkspace: vi.fn().mockResolvedValue({ library_item_id: video, position_ms: 0, region: null }),
    saveWatchPosition: vi.fn(), getParts: vi.fn(() => pending),
    saveStudyRegion: vi.fn().mockResolvedValue({ library_item_id: video, position_ms: 0, region }),
  };
  const container = { playback } as unknown as AppContainer;
  const rendered = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ContainerProvider container={container}><MemoryRouter initialEntries={[`/library/videos/${video}/watch`]}>
      <Routes><Route element={<AppShell />}><Route path="/library/videos/:libraryItemId/watch" element={<WatchScreen />} /></Route></Routes>
    </MemoryRouter></ContainerProvider></QueryClientProvider>);
  await screen.findByTitle("Synthetic video");
  await userEvent.click(screen.getByRole("button", { name: "Open agent" }));
  await userEvent.click(await screen.findByRole("button", { name: "Synthetic turn 0" }));
  await act(async () => resolveParts({ transcript_id: sentence, source: "ai", parts: [{ ...region, title: "First part" }] }));
  await waitFor(() => expect(playback.saveStudyRegion).toHaveBeenCalled());
  await screen.findByText("First part");
  expect(screen.getByRole("button", { name: "Synthetic turn 1" })).toBeVisible();
  expect(lifecycle.mounted).toHaveBeenCalledTimes(1);
  expect(lifecycle.closed).not.toHaveBeenCalled();
  rendered.unmount();
  expect(lifecycle.closed).toHaveBeenCalledTimes(1);
  vi.unstubAllGlobals();
});
