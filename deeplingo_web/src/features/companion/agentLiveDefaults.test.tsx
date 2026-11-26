import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentConversation } from "./AgentConversation";

const captured = vi.hoisted(() => ({ live: vi.fn(), fallback: vi.fn() }));
vi.mock("./RealtimeScreen", () => ({ RealtimeScreen: (props: { onFallback: () => void }) => {
  captured.live(props);
  return <button onClick={props.onFallback}>Live unavailable — use recorded turns</button>;
} }));
vi.mock("./CompanionConversation", () => ({ CompanionConversation: (props: object) => {
  captured.fallback(props);
  return <p>Recorded voice</p>;
} }));

describe("one embedded Tata", () => {
  it("starts with Live and preserves video context when explicitly choosing fallback", async () => {
    captured.live.mockClear(); captured.fallback.mockClear();
    const watching = { item: "owned-video", segmentId: () => "current-segment", onTalk: vi.fn() };
    const onPractice = vi.fn();
    render(<AgentConversation entry="video" item={watching.item} watching={watching} onPractice={onPractice} />);
    const fallback = await screen.findByRole("button", { name: /Live unavailable/ });
    expect(captured.fallback).not.toHaveBeenCalled();
    expect(captured.live.mock.calls.at(-1)?.[0].watching).toBe(watching);
    await userEvent.click(fallback);
    expect(await screen.findByText("Recorded voice")).toBeVisible();
    expect(captured.fallback.mock.calls.at(-1)?.[0]).toMatchObject({ watching, onPractice, entry: "video", item: "owned-video" });
    expect(screen.queryByRole("button", { name: /Live unavailable/ })).toBeNull();
  });
});
