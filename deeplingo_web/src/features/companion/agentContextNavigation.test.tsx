import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AgentDock } from "./AgentDock";

const BOOK = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const VIDEO = "33333333-3333-4333-8333-333333333333";
const SEGMENT = "44444444-4444-4444-8444-444444444444";

vi.mock("./AgentConversation", () => ({ AgentConversation: (props: { onTopicChange?: (id: string) => void }) =>
  <button onClick={() => props.onTopicChange?.(OTHER)}>Choose another topic</button>,
}));

describe("expanding Tata preserves its selectors", () => {
  it("keeps the notebook and a topic chosen inside the panel", async () => {
    render(<MemoryRouter initialEntries={[`/words/lists/${BOOK}`]}><AgentDock onClose={vi.fn()} /></MemoryRouter>);
    const link = screen.getByRole("link", { name: "Open full conversation" });
    expect(new URL(link.getAttribute("href")!, "http://test").searchParams.get("topic")).toBe(BOOK);
    await userEvent.click(screen.getByRole("button", { name: "Choose another topic" }));
    expect(new URL(link.getAttribute("href")!, "http://test").searchParams.get("topic")).toBe(OTHER);
  });

  it("keeps the current video sentence when expanding the Watch panel", () => {
    render(<MemoryRouter initialEntries={[`/library/videos/${VIDEO}/watch`]}>
      <AgentDock onClose={vi.fn()} segmentId={SEGMENT} />
    </MemoryRouter>);
    const link = screen.getByRole("link", { name: "Open full conversation" });
    const params = new URL(link.getAttribute("href")!, "http://test").searchParams;
    expect(params.get("item")).toBe(VIDEO);
    expect(params.get("segment")).toBe(SEGMENT);
  });
});
