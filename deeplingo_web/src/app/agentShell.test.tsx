import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useContext, useEffect } from "react";
import { AppShell } from "./AppShell";
import { AgentPanelContext } from "./AgentPanelContext";

vi.mock("./AuthProvider", () => ({ useAuth: () => ({ signOut: vi.fn() }) }));
vi.mock("../features/companion/AgentConversation", () => ({
  AgentConversation: () => <><p>Agent reply</p><p>Learner reply</p></>,
}));

beforeEach(() => vi.stubGlobal("scrollTo", vi.fn()));
afterEach(() => vi.unstubAllGlobals());

function mount(path = "/words") {
  return render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route element={<AppShell />}><Route path={path} element={<h1>My words stay visible</h1>} /></Route>
  </Routes></MemoryRouter>);
}

const ITEM = "aaaaaaaa-2222-3333-4444-555555555555";
const SEGMENT = "00000000-0000-4000-8000-000000000004";

// Stands in for the watch page, which names its study part on the launcher.
function PartScreen({ on }: { on: boolean }) {
  const onLauncherChange = useContext(AgentPanelContext)?.onLauncherChange;
  useEffect(() => {
    onLauncherChange?.(on ? { title: "Talk about part 4", subtitle: "Tata knows what you are practising", segmentId: SEGMENT } : null);
  }, [on, onLauncherChange]);
  return <h1>Watching</h1>;
}

describe("Agent in the app shell", () => {
  it("a screen with a study part turns the launcher into a talk about that part", () => {
    const path = `/library/videos/${ITEM}/watch`;
    const view = render(<MemoryRouter initialEntries={[path]}><Routes>
      <Route element={<AppShell />}><Route path={path} element={<PartScreen on />} /></Route>
    </Routes></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Talk about part 4" }))
      .toHaveAttribute("href", `/agent?mode=voice&entry=video&item=${ITEM}&segment=${SEGMENT}`);
    expect(screen.getByText("Tata knows what you are practising")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Talk with Tata" })).toBeNull();
    view.rerender(<MemoryRouter initialEntries={[path]}><Routes>
      <Route element={<AppShell />}><Route path={path} element={<PartScreen on={false} />} /></Route>
    </Routes></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Talk with Tata" })).toBeInTheDocument();
  });

  it.each(["/review/en", "/notebook/all/flashcards"])("keeps the launcher bar off %s, where it would cover the buttons", (path) => {
    render(<MemoryRouter initialEntries={[path]}><Routes>
      <Route element={<AppShell />}><Route path={path} element={<h1>Study</h1>} /></Route>
    </Routes></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Study" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Tata" })).toBeNull();
  });

  it("opens the shared conversation over the current screen and restores focus on close", async () => {
    mount();
    const launcher = screen.getByRole("button", { name: "Open agent" });
    expect(screen.queryByRole("link", { name: "Speaking" })).not.toBeInTheDocument();
    // Review is a study mode inside the notebook, not a tab of its own.
    expect(screen.queryByRole("link", { name: "Review" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Notebook" })).toHaveAttribute("href", "/words/lists");
    expect(within(screen.getByRole("navigation", { name: "Primary" })).getAllByRole("link")).toHaveLength(4);
    expect(screen.queryByRole("link", { name: "Library" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Progress" })).toHaveAttribute("href", "/progress");
    expect(screen.getByRole("link", { name: "Talk with Tata" })).toHaveAttribute("href", "/agent?mode=voice&entry=home");
    await userEvent.click(launcher);
    const panel = await screen.findByRole("dialog", { name: "Agent conversation" });
    expect(within(panel).getByText("Agent reply")).toBeVisible();
    expect(within(panel).getByText("Learner reply")).toBeVisible();
    expect(screen.getByRole("heading", { name: "My words stay visible" })).toBeVisible();
    expect(within(panel).getByRole("link", { name: "Open full conversation" })).toHaveAttribute("href", "/agent?entry=home");
    await userEvent.click(within(panel).getByRole("button", { name: "Close agent" }));
    expect(screen.queryByRole("dialog", { name: "Agent conversation" })).not.toBeInTheDocument();
    expect(launcher).toHaveFocus();
  });

  it.each(["ctrlKey", "metaKey"])("toggles the panel with %s + L and closes with Escape", async modifier => {
    mount();
    fireEvent.keyDown(window, { key: "l", [modifier]: true });
    await screen.findByRole("dialog", { name: "Agent conversation" });
    fireEvent.keyDown(window, { key: "l", [modifier]: true });
    expect(screen.queryByRole("dialog", { name: "Agent conversation" })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "l", [modifier]: true });
    await screen.findByRole("dialog", { name: "Agent conversation" });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Agent conversation" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open agent" })).toHaveFocus();
  });
});
