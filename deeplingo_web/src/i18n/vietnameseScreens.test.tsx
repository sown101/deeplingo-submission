import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { ContainerProvider, type AppContainer } from "../app/container";
import { GrammarShelf } from "../features/words/GrammarShelf";
import { I18nProvider } from "./i18n";

// The screens that used to hold Vietnamese text now take English keys: a Vietnamese learner must still see the same words.
function mount(container: object, children: React.ReactNode) {
  render(<I18nProvider language="vi"><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ContainerProvider container={container as AppContainer}>{children}</ContainerProvider>
  </QueryClientProvider></I18nProvider>);
}

describe("Vietnamese interface on the newest screens (FR-6.1)", () => {
  it("shows the notebook's Grammar tab in Vietnamese", async () => {
    const overview = { languageCode: "en", levels: ["A1"], level: "A1", redo: [],
      topics: [{ key: "t", title: "Chủ đề" }],
      points: [{ key: "en.a1.t", title: "Điểm", topicKey: "t", lesson: null, exerciseCount: 4, attempts: 3, correctCount: 2,
        incorrectCount: 1, lessonLearnedAt: null }] };
    mount({ review: { grammar: async () => overview } }, <GrammarShelf toggle={null} language="en" />);
    expect(await screen.findByRole("button", { name: "Luyện ngay" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Chủ đề" })).toBeInTheDocument();
    expect(screen.getByText("2 đúng, 1 sai")).toBeInTheDocument();
    expect(screen.getByText("Câu đúng")).toBeInTheDocument();
  });
});
