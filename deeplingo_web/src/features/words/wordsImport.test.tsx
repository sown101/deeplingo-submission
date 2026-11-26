import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import type { ApiClient } from "../../lib/api/apiClient";
import { ApiError } from "../../lib/api/errors";
import { MyWordsScreen } from "./MyWordsScreen";
import { WordsApi } from "./wordsApi";
import { parseMyWordsView } from "./wordsModels";

const importedWord = {
  concept_id: "33333333-3333-3333-3333-333333333333", language_code: "en",
  text: "airport", kind: "word", gloss: "A place where aircraft land.",
  list: "saved", saved: true, save_source: "import", status: "backlog", rung: 0,
};

describe("words imported from a named list", () => {
  it("renders the real API source on a level page instead of a load error", async () => {
    const get = vi.fn(async () => ({ words: [importedWord], summary: null }));
    const words = new WordsApi({ get } as unknown as ApiClient);
    const container = {
      words,
      notebook: {
        details: async () => ({ conceptId: importedWord.concept_id, text: "airport", traditional: null, reading: null, level: null, senses: [], characters: [], compounds: [] }),
        images: async () => [],
      },
      onboarding: { loadProfile: async () => ({ learning_language: "en", support_language: "vi" }) },
    } as unknown as AppContainer;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter initialEntries={["/words?level=0"]}>
        <QueryClientProvider client={client}>
          <ContainerProvider container={container}><MyWordsScreen /></ContainerProvider>
        </QueryClientProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("airport")).toBeInTheDocument();
    expect(screen.queryByText("Your words could not be loaded.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open airport" }));
    expect(await screen.findByText("Learning", { exact: true })).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/learner/me/words?language_code=en");
  });

  it("keeps the import source when an imported word is activated", async () => {
    const put = vi.fn(async () => ({ ...importedWord, status: "active" }));
    const words = new WordsApi({ put } as unknown as ApiClient);
    await expect(words.setStatus(importedWord.concept_id, "active"))
      .resolves.toMatchObject({ saveSource: "import", status: "active" });
  });

  it("still rejects unsupported save sources", () => {
    expect(() => parseMyWordsView({ words: [{ ...importedWord, save_source: "unsupported" }] }))
      .toThrow(ApiError);
  });
});
