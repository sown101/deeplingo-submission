import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import type { Progress } from "./progressApi";
import { ProgressScreen } from "./ProgressScreen";

const BASE: Progress = {
  language: null, languages: ["en", "zh"],
  streak: { current: 3, longest: 5, active_days: 7 },
  calendar: { days: [], active_days: 7, current_streak_days: 3 },
  cards: [
    { language_code: "en", total: 5, due: 2, new: 1, learning: 1, review: 2, relearning: 1 },
    { language_code: "zh", total: 3, due: 1, new: 1, learning: 0, review: 2, relearning: 0 },
  ],
  accuracy: [{ kind: "choice", attempts: 4, correct: 3, accuracy: 75 }],
  pronunciation: [
    { date: "2026-10-20", pronunciation: 60, accuracy: 55, fluency: 65, completeness: null, prosody: null, sessions: 1 },
    { date: "2026-10-31", pronunciation: 82.4, accuracy: 77, fluency: 88, completeness: 96, prosody: 71, sessions: 2 }],
  weak_words: ["water", "three"],
  grammar: { learned: 2, done_correctly: 1 }, regions_completed: 3, speaking: { sessions: 2, minutes: 4.5, weeks: [{ week_start: "2026-11-09", minutes: 4.5 }] },
};
const CHINESE: Progress = { ...BASE, language: "zh", languages: ["zh"], cards: [BASE.cards[1]], accuracy: [{ kind: "cloze", attempts: 2, correct: 0, accuracy: 0 }],
  streak: { current: 1, longest: 1, active_days: 1 }, calendar: { days: [], active_days: 1, current_streak_days: 1 } };

function mount(loadProgress = vi.fn(async (language?: string) => language === "zh" ? CHINESE : BASE)) {
  render(<MemoryRouter><QueryClientProvider client={new QueryClient()}>
    <ContainerProvider container={{ progress: { loadProgress } } as unknown as AppContainer}><ProgressScreen /></ContainerProvider>
  </QueryClientProvider></MemoryRouter>);
  return loadProgress;
}

it("shows the learner's numbers from the one progress endpoint", async () => {
  const load = mount();
  const streak = (await screen.findByText("Current streak")).parentElement!;
  expect(await within(streak).findByText("3")).toBeInTheDocument();
  expect(load).toHaveBeenCalledWith(undefined);
  const cards = screen.getByRole("region", { name: "Cards" });
  expect(cards.querySelector(".progress-total")).toHaveTextContent("8 cards · 3 due now"); // both decks
  expect(within(within(cards).getByText("Review").parentElement!).getByText("4")).toBeInTheDocument();
  const accuracy = screen.getByRole("region", { name: "Accuracy" });
  expect(within(accuracy).getByText("75%")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Grammar" })).getByText("2")).toBeInTheDocument();
  expect(await screen.findAllByText("82")).toHaveLength(2); // the latest score and the table
  const pronunciation = screen.getByRole("region", { name: "Pronunciation" });
  for (const metric of ["Pronunciation score", "Accuracy", "Fluency", "Completeness", "Prosody"]) {
    expect(within(pronunciation).getAllByText(metric).length).toBeGreaterThan(0);
  }
  expect(within(pronunciation).getByText("water")).toBeInTheDocument();
  expect(within(pronunciation).getAllByText("96")).toHaveLength(2); // completeness of the latest day
});

it("filters by language and asks the server for that language only", async () => {
  const load = mount();
  await screen.findByText("Current streak");
  const filter = await screen.findByRole("group", { name: "Language" });
  expect(within(filter).getByRole("button", { name: "All languages" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(filter).getAllByRole("button")[2]);
  expect(await within(screen.getByRole("region", { name: "Accuracy" })).findByText("0%")).toBeInTheDocument();
  expect(load).toHaveBeenLastCalledWith("zh");
  const cards = screen.getByRole("region", { name: "Cards" });
  expect(cards.querySelector(".progress-total")).toHaveTextContent("3 cards · 1 due now");
  // The filter keeps every language the learner studies.
  expect(within(screen.getByRole("group", { name: "Language" })).getAllByRole("button")).toHaveLength(3);
});

it("narrows the heatmap and the facts to the chosen period", async () => {
  mount();
  expect(await screen.findByText("0 of 365 days")).toBeInTheDocument();
  expect(document.querySelectorAll(".act-heatmap__grid .act-cell")).toHaveLength(53 * 7);
  fireEvent.click(screen.getByRole("button", { name: "1 month" }));
  expect(screen.getByText("0 of 30 days")).toBeInTheDocument();
  expect(document.querySelectorAll(".act-heatmap__grid .act-cell")).toHaveLength(5 * 7);
});

it("offers a retry when the progress cannot be loaded and shows the numbers once it loads", async () => {
  const loadProgress = vi.fn(async (_language?: string) => BASE);
  loadProgress.mockRejectedValueOnce(new Error("private provider detail"));
  mount(loadProgress);
  expect(await screen.findByText("Your progress could not be loaded.")).toBeInTheDocument();
  expect(screen.queryByText("private provider detail")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry progress" }));
  const streak = (await screen.findByText("Current streak")).parentElement!;
  expect(await within(streak).findByText("3")).toBeInTheDocument();
  expect(screen.queryByText("Your progress could not be loaded.")).not.toBeInTheDocument();
  expect(loadProgress).toHaveBeenCalledTimes(2);
});

it("says that the speaking time covers the last 12 months whatever period is chosen", async () => {
  mount();
  expect(await screen.findByText("2 speaking sessions in the last 12 months")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "1 month" }));
  expect(screen.getByText("2 speaking sessions in the last 12 months")).toBeInTheDocument();
});

it("keeps every pronunciation score readable without the chart and shows a day on hover", async () => {
  mount();
  const table = await screen.findByRole("table", { name: "Pronunciation scores by day" });
  expect(within(table).getByText("2026-10-20")).toBeInTheDocument();
  const plot = document.querySelector(".progress-plot")!;
  fireEvent.pointerMove(plot, { clientX: 0 });
  expect(document.querySelector(".progress-tip")).toHaveTextContent("20/10");
  fireEvent.pointerLeave(plot);
  expect(document.querySelector(".progress-tip")).toBeNull();
});

it("draws the activity, speaking and card-state charts", async () => {
  mount();
  await within(await screen.findByRole("region", { name: "Cards" })).findByText("Review");
  const activity = screen.getByRole("region", { name: "Activity over time" });
  expect(activity.querySelectorAll(".progress-bars i")).toHaveLength(30);
  fireEvent.click(screen.getByRole("button", { name: "Weeks" }));
  expect(activity.querySelectorAll(".progress-bars i")).toHaveLength(26);
  expect(screen.getByRole("region", { name: "Speaking per week" }).querySelectorAll(".progress-bars i")).toHaveLength(12);
  const cards = screen.getByRole("region", { name: "Cards" });
  expect(cards.querySelectorAll(".progress-deck")).toHaveLength(2); // one stacked bar per language
  expect(within(screen.getByRole("region", { name: "Accuracy" })).getByText("3 of 4")).toBeInTheDocument();
});
