import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomeEvidence } from "./HomeEvidence";
import type { Progress } from "../progress/progressApi";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 31, 12));
});
afterEach(() => vi.useRealTimers());

const PROGRESS: Progress = {
  language: null, languages: ["en"],
  streak: { current: 1, longest: 2, active_days: 3 },
  calendar: {
    days: [{ date: "2026-10-25", attempts: 100 }, { date: "2026-10-26", attempts: 2 }, { date: "2026-10-31", attempts: 5 }],
    active_days: 3, current_streak_days: 1,
  },
  cards: [
    { language_code: "en", total: 6, due: 3, new: 2, learning: 1, review: 3, relearning: 0 },
    { language_code: "zh", total: 2, due: 1, new: 0, learning: 0, review: 1, relearning: 1 },
  ],
  accuracy: [], pronunciation: [], weak_words: [], grammar: { learned: 0, done_correctly: 0 }, regions_completed: 0, speaking: { sessions: 0, minutes: 0, weeks: [] },
};

function mount(progress: Progress | undefined = PROGRESS, failed = false) {
  const retry = vi.fn();
  render(<MemoryRouter><HomeEvidence progress={progress} failed={failed} retry={retry} /></MemoryRouter>);
  return { retry };
}

describe("Home summary card", () => {
  it("draws a year of real activity with the streak facts and links it to Progress", () => {
    mount();
    expect(screen.getByRole("img", { name: "107 practice attempts in the last 53 weeks" })).toBeInTheDocument();
    expect(document.querySelectorAll(".act-heatmap__grid .act-cell")).toHaveLength(53 * 7);
    expect(document.querySelector('[title="2026-10-25: 100"]')).toHaveClass("level-4");
    expect(document.querySelector('[title="2026-10-31: 5"]')).toHaveClass("today");
    expect(document.querySelector(".act-facts")).toHaveTextContent("Current streak 1 days · Longest 2 days · Practised on 1% of days · Average 36/day");
    expect(screen.getByRole("link", { name: "Open Progress" })).toHaveAttribute("href", "/progress");
  });

  it("sums the cards of every language by state and opens review", () => {
    mount();
    const list = screen.getByRole("list", { name: "8 cards" });
    expect(list).toHaveTextContent("New2");
    expect(list).toHaveTextContent("Review4");
    expect(list).toHaveTextContent("Relearning1");
    expect(screen.getByText("4 due now")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review now" })).toHaveAttribute("href", "/review/quick");
  });

  it("isolates a failure and offers retry without exposing private errors", async () => {
    const { retry } = mount(undefined, true);
    expect(screen.getByText("Your activity could not be loaded.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
