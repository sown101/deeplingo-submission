import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n/i18n";
import { AgentDock } from "./AgentDock";

// The conversation itself is covered elsewhere; here it only reports what Tata is doing.
vi.mock("./AgentConversation", () => ({
  AgentConversation: ({ onPhaseChange, onMicError }: { onPhaseChange: (phase: string) => void; onMicError: (blocked: boolean) => void }) => <>
    <button onClick={() => onPhaseChange("thinking")}>thinking</button>
    <button onClick={() => onPhaseChange("recording")}>recording</button>
    <button onClick={() => { onMicError(true); onPhaseChange("failed"); }}>mic blocked</button>
    <button onClick={() => { onMicError(false); onPhaseChange("starting"); }}>retry</button>
  </>,
}));

function mount() {
  render(<I18nProvider language="vi"><MemoryRouter><AgentDock onClose={vi.fn()} /></MemoryRouter></I18nProvider>);
  return screen.findByRole("dialog");
}

describe("Tata panel states", () => {
  it("says it is answering with the speaking face while a turn is processed, then listening", async () => {
    const panel = await mount();
    expect(await within(panel).findByText("Sẵn sàng")).toBeVisible();
    expect(panel.querySelector("img")?.getAttribute("src")).toContain("otter-idle");
    await userEvent.click(within(panel).getByText("thinking"));
    expect(within(panel).getByText("Đang trả lời…")).toBeVisible();
    expect(panel.querySelector("img")?.getAttribute("src")).toContain("otter-speak");
    await userEvent.click(within(panel).getByText("recording"));
    expect(within(panel).getByText("Đang nghe…")).toBeVisible();
    expect(panel.querySelector("img")?.getAttribute("src")).toContain("otter-listen");
  });

  it("shows a microphone alert instead of an unexplained failure, and clears it on a new try", async () => {
    const panel = await mount();
    await userEvent.click(within(panel).getByText("mic blocked"));
    expect(within(panel).getByRole("alert")).toHaveTextContent("Không dùng được micro");
    expect(within(panel).queryByText("Không khả dụng")).not.toBeInTheDocument();
    await userEvent.click(within(panel).getByText("retry"));
    expect(within(panel).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(panel).getByText("Đang bắt đầu cuộc trò chuyện…")).toBeVisible();
  });
});
