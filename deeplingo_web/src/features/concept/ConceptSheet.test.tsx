import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ConceptSheet } from "./ConceptSheet";
import { ContainerProvider } from "../../app/container";
import type { AppContainer } from "../../app/container";

const LO_ID = "55555555-6666-7777-8888-999999999999";
const LIB_ID = "11111111-1111-1111-1111-111111111111";

const conceptPayload = {
  library_item_id: LIB_ID,
  learning_object_id: LO_ID,
  expression: "Elephants",
  occurrence_text: "Elephants",
  source_segment_text: "Elephants can live to seventy years old.",
  start_codepoint: 0,
  end_codepoint: 9,
  learning_language_code: "en",
  support_language_code: "vi",
  contextual_meaning: "con voi",
  explanation: null,
  meaning_provenance: "unverified",
  dictionary_sense: null,
};

function fakeContainer(payload: object = conceptPayload): AppContainer {
  return {
    playback: {
      getConcept: vi.fn().mockResolvedValue(payload),
    },
  } as unknown as AppContainer;
}

function renderHarness(ui: React.ReactElement): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(<MemoryRouter><QueryClientProvider client={queryClient}>{ui}</QueryClientProvider></MemoryRouter>);
}

function SheetHarness(): React.ReactElement {
  const [open, setOpen] = useState(true);
  return (
    <ContainerProvider container={fakeContainer()}>
      <button type="button" onClick={() => setOpen(true)}>
        Open concept
      </button>
      {open ? <ConceptSheet libraryItemId={LIB_ID} learningObjectId={LO_ID} onClose={() => setOpen(false)} /> : null}
    </ContainerProvider>
  );
}

describe("ConceptSheet modal semantics", () => {
  it("renders learner-safe content without authority fields", async () => {
    renderHarness(<SheetHarness />);
    expect(await screen.findByText("Elephants")).toBeInTheDocument();
    expect(screen.getByText("con voi")).toBeInTheDocument();
    expect(screen.getByText("Elephants can live to seventy years old.")).toBeInTheDocument();
    // No Concept ID, sense_key, mastery or FSRS internals are ever rendered.
    expect(screen.queryByText(/concept_id/i)).toBeNull();
    expect(screen.queryByText(/sense_key/i)).toBeNull();
    expect(screen.queryByText(/mastery|fsrs|review_state/i)).toBeNull();
  });

  it("moves focus into the dialog on open", async () => {
    renderHarness(<SheetHarness />);
    await screen.findByText("Concept");
    const dialog = screen.getByRole("dialog", { name: "Concept" });
    expect(dialog).toHaveFocus();
  });

  it("closes on Escape and restores focus to the opener", async () => {
    renderHarness(<SheetHarness />);
    const opener = screen.getByRole("button", { name: "Open concept" });
    opener.focus();
    fireEvent.click(opener); // mounts the sheet; opener had focus
    await screen.findByRole("dialog", { name: "Concept" });

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Concept" })).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("keeps Tab cycling inside the dialog", async () => {
    const user = userEvent.setup();
    renderHarness(<SheetHarness />);
    const dialog = await screen.findByRole("dialog", { name: "Concept" });
    const close = screen.getByRole("button", { name: "Close" });
    close.focus();

    // Tab from the last focusable wraps to the dialog container/focusable set.
    await user.tab();
    const inside = dialog.contains(document.activeElement) || document.activeElement === dialog;
    expect(inside).toBe(true);

    // Shift+Tab from the container/focusable set wraps back inside too.
    await user.tab({ shift: true });
    expect(
      dialog.contains(document.activeElement) || document.activeElement === dialog,
    ).toBe(true);
  });

  it("announces loading with a status role", () => {
    const container = {
      playback: { getConcept: vi.fn(() => new Promise(() => undefined)) },
    } as unknown as AppContainer;
    renderHarness(
      <ContainerProvider container={container}>
        <ConceptSheet libraryItemId={LIB_ID} learningObjectId={LO_ID} onClose={vi.fn()} />
      </ContainerProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading concept…");
  });

  it("offers a safe retry on load failure without exposing diagnostics", async () => {
    const container = {
      playback: { getConcept: vi.fn().mockRejectedValue(new Error("HTTP 500 raw server internals")) },
    } as unknown as AppContainer;
    renderHarness(
      <ContainerProvider container={container}>
        <ConceptSheet libraryItemId={LIB_ID} learningObjectId={LO_ID} onClose={vi.fn()} />
      </ContainerProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This concept could not be loaded. Please try again.",
    );
    expect(screen.queryByText(/HTTP 500|server internals/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("labels an AI meaning as not checked against a dictionary", async () => {
    renderHarness(<SheetHarness />);
    expect(await screen.findByText("AI explanation, not checked against a dictionary")).toBeInTheDocument();
    expect(screen.queryByText("Dictionary")).toBeNull();
  });

  it("shows the dictionary sense with its source and licence links", async () => {
    const payload = {
      ...conceptPayload,
      meaning_provenance: "dictionary",
      dictionary_sense: {
        headword: "elephant",
        reading: null,
        part_of_speech: "noun",
        definition: "A mammal of the order Proboscidea.",
        source_name: "Wiktionary",
        source_url: "https://en.wiktionary.org/wiki/elephant",
        license_name: "CC BY-SA 4.0",
        license_url: "https://creativecommons.org/licenses/by-sa/4.0/",
      },
    };
    renderHarness(
      <ContainerProvider container={fakeContainer(payload)}>
        <ConceptSheet libraryItemId={LIB_ID} learningObjectId={LO_ID} onClose={vi.fn()} />
      </ContainerProvider>,
    );
    expect(await screen.findByText("From the dictionary")).toBeInTheDocument();
    expect(screen.getByText("A mammal of the order Proboscidea.")).toBeInTheDocument();
    const source = screen.getByRole("link", { name: "Wiktionary" });
    expect(source).toHaveAttribute("href", "https://en.wiktionary.org/wiki/elephant");
    expect(source).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: "CC BY-SA 4.0" })).toHaveAttribute(
      "href", "https://creativecommons.org/licenses/by-sa/4.0/",
    );
  });
});
