import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { LookupSheet } from "./LookupSheet";
import { ContainerProvider } from "../../app/container";
import type { AppContainer } from "../../app/container";
import type { TranscriptSegmentView } from "../../lib/api/dto";
import { parseWordLookupView } from "../video/videoModels";
import { ApiError } from "../../lib/api/errors";

const LIB_ID = "11111111-1111-1111-1111-111111111111";
const SEGMENT: TranscriptSegmentView = {
  segment_id: "22222222-2222-2222-2222-222222222222",
  sequence: 1,
  text: "She finally gave up smoking.",
  start_ms: 0,
  end_ms: 2000,
  translation: null,
  romanizations: [],
  learning_objects: [],
};

const giveUp = {
  segment_id: SEGMENT.segment_id,
  selection_start: 17,
  selection_end: 19,
  unit_start: 12,
  unit_end: 19,
  unit_text: "gave up",
  unit_kind: "phrase",
  selection_is_part: true,
  headword: "give up",
  reading: null,
  part_of_speech: "verb",
  dictionary_gloss: "To stop or quit (an activity, etc.).",
  sense_id: "enwikt:giveup1",
  meaning: "từ bỏ",
  note: "Thường dùng cho một thói quen.",
  meaning_provenance: "translated_from_sense",
  level: null,
  source: {
    name: "Wiktionary",
    license_name: "CC BY-SA 4.0",
    license_url: "https://creativecommons.org/licenses/by-sa/4.0/",
    entry_url: "https://en.wiktionary.org/wiki/give_up",
  },
};

function renderSheet(lookup: ReturnType<typeof vi.fn>) {
  const container = { playback: { lookup } } as unknown as AppContainer;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ContainerProvider container={container}>
        <LookupSheet libraryItemId={LIB_ID} segment={SEGMENT} span={{ start: 17, end: 19 }} onClose={vi.fn()} />
      </ContainerProvider>
    </QueryClientProvider>,
  );
}

describe("LookupSheet", () => {
  it("says the selection is part of a phrase and credits the dictionary", async () => {
    const lookup = vi.fn().mockResolvedValue(parseWordLookupView(giveUp, SEGMENT.text));
    renderSheet(lookup);
    expect(await screen.findByText("từ bỏ")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("“up” is part of the phrase gave up (give up).");
    expect(screen.getByText("From the dictionary")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Wiktionary" })).toHaveAttribute("href", "https://en.wiktionary.org/wiki/give_up");
    expect(lookup).toHaveBeenCalledWith(LIB_ID, SEGMENT, { start: 17, end: 19 });
  });

  it("labels an AI meaning as unverified and explains a rate limit", async () => {
    const unverified = { ...giveUp, meaning_provenance: "ai_unverified", sense_id: null, dictionary_gloss: null, source: null };
    renderSheet(vi.fn().mockResolvedValue(parseWordLookupView(unverified, SEGMENT.text)));
    expect(await screen.findByText("AI explanation, not checked against a dictionary")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("explains a rate limit", async () => {
    renderSheet(vi.fn().mockRejectedValue(new ApiError("server", 429, { message: "x" })));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many lookups");
  });
});

describe("parseWordLookupView", () => {
  it("rejects a unit that is not the segment text or does not contain the selection", () => {
    expect(() => parseWordLookupView({ ...giveUp, unit_text: "give up" }, SEGMENT.text)).toThrow(ApiError);
    expect(() => parseWordLookupView({ ...giveUp, unit_end: 18, unit_text: "gave u" }, SEGMENT.text)).toThrow(ApiError);
  });

  it("rejects a dictionary credit without its text, insecure links and unknown provenance", () => {
    expect(() => parseWordLookupView({ ...giveUp, dictionary_gloss: null }, SEGMENT.text)).toThrow(ApiError);
    expect(() =>
      parseWordLookupView({ ...giveUp, source: { ...giveUp.source, entry_url: "http://x.example" } }, SEGMENT.text),
    ).toThrow(ApiError);
    expect(() => parseWordLookupView({ ...giveUp, meaning_provenance: "guess" }, SEGMENT.text)).toThrow(ApiError);
    expect(() => parseWordLookupView({ ...giveUp, meaning: null }, SEGMENT.text)).toThrow(ApiError);
  });
});
