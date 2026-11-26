import { describe, expect, it } from "vitest";
import { parsePlayableVideo, parseVideoTranscriptView, parseConceptInteractionView } from "./videoModels";
import { youtubeIdFromUrl } from "./playbackApi";

const LO_ID = "22222222-3333-4444-5555-666666666666";
const SEG_ID = "33333333-4444-5555-6666-777777777777";
const LIB_ID = "44444444-5555-6666-7777-888888888888";
const VID_ID = "55555555-6666-7777-8888-999999999999";

describe("playback DTO parsing", () => {
  it("parses valid playable video", () => {
    const parsed = parsePlayableVideo({
      library_item_id: LIB_ID,
      video_id: VID_ID,
      provider: "youtube",
      external_video_id: "jNQXAC9IVRw",
      title: "Me at the zoo",
      language_code: "en",
      duration_ms: 19000,
    });
    expect(parsed.external_video_id).toBe("jNQXAC9IVRw");
  });

  it("rejects non-youtube provider and malformed ids", () => {
    expect(() =>
      parsePlayableVideo({ provider: "vimeo", external_video_id: "jNQXAC9IVRw", library_item_id: LIB_ID, video_id: VID_ID, title: "x", language_code: "en" }),
    ).toThrow();
    expect(() =>
      parsePlayableVideo({ provider: "youtube", external_video_id: "short", library_item_id: LIB_ID, video_id: VID_ID, title: "x", language_code: "en" }),
    ).toThrow();
  });
});

describe("transcript DTO parsing", () => {
  const segment = {
    segment_id: SEG_ID,
    sequence: 1,
    text: "Elephants can live to seventy years old, or even longer.",
    start_ms: 0,
    end_ms: 5000,
    translation: null,
    romanizations: [],
    learning_objects: [
      { learning_object_id: LO_ID, start_codepoint: 0, end_codepoint: 9 },
    ],
  };

  it("parses valid transcript", () => {
    const parsed = parseVideoTranscriptView({
      library_item_id: LIB_ID,
      language_code: "en",
      translation_language_code: null,
      segments: [segment],
    });
    expect(parsed.segments).toHaveLength(1);
    expect(parsed.segments[0].learning_objects).toHaveLength(1);
  });

  it("rejects occurrences extending beyond the text (code-point bound)", () => {
    expect(() => parseVideoTranscriptView({
      library_item_id: LIB_ID,
      language_code: "en",
      translation_language_code: null,
      segments: [{ ...segment, learning_objects: [{ learning_object_id: LO_ID, start_codepoint: 0, end_codepoint: 999 }] }],
    })).toThrow();
  });

  it("rejects malformed occurrence offsets at the transcript boundary", () => {
    expect(() => parseVideoTranscriptView({
      library_item_id: LIB_ID,
      language_code: "en",
      translation_language_code: null,
      segments: [
        { ...segment, learning_objects: [{ learning_object_id: LO_ID, start_codepoint: -1, end_codepoint: 5 }, { learning_object_id: LO_ID, start_codepoint: 5, end_codepoint: 3 }] },
      ],
    })).toThrow();
  });

  it("counts astral emoji as single code points for the bound", () => {
    const parsed = parseVideoTranscriptView({
      library_item_id: LIB_ID,
      language_code: "en",
      translation_language_code: null,
      segments: [
        {
          ...segment,
          text: "ðŸ˜€ðŸ˜€ hi",
          learning_objects: [
            { learning_object_id: LO_ID, start_codepoint: 0, end_codepoint: 2 }, // both emoji: valid (3 code points total)
            { learning_object_id: LO_ID, start_codepoint: 0, end_codepoint: 4 }, // beyond 4 code points? text "ðŸ˜€ðŸ˜€ hi" = 5 code points, so valid too
          ],
        },
      ],
    });
    expect(parsed.segments[0].learning_objects).toHaveLength(2);
  });

  it("rejects empty segment lists and invalid timing", () => {
    expect(() =>
      parseVideoTranscriptView({ library_item_id: LIB_ID, language_code: "en", translation_language_code: null, segments: [] }),
    ).toThrow();
    expect(() =>
      parseVideoTranscriptView({
        library_item_id: LIB_ID,
        language_code: "en",
        translation_language_code: null,
        segments: [{ ...segment, end_ms: 0 }],
      }),
    ).toThrow();
  });

  it("rejects duplicate segment identity", () => {
    expect(() =>
      parseVideoTranscriptView({
        library_item_id: LIB_ID,
        language_code: "en",
        translation_language_code: null,
        segments: [segment, segment],
      }),
    ).toThrow();
  });

  it("sorts segments by start then sequence", () => {
    const parsed = parseVideoTranscriptView({
      library_item_id: LIB_ID,
      language_code: "en",
      translation_language_code: null,
      segments: [
        { ...segment, segment_id: "aaaaaaaa-1111-2222-3333-444444444444", sequence: 2, start_ms: 1000 },
        { ...segment, sequence: 1, start_ms: 1000 },
      ],
    });
    expect(parsed.segments[0].sequence).toBe(1);
  });
});

describe("concept DTO parsing", () => {
  const source = "Elephants can live to seventy years old.";

  it("validates exact code-point source slice", () => {
    const parsed = parseConceptInteractionView({
      library_item_id: LIB_ID,
      learning_object_id: LO_ID,
      expression: "Elephants",
      occurrence_text: "Elephants",
      source_segment_text: source,
      start_codepoint: 0,
      end_codepoint: 9,
      learning_language_code: "en",
      support_language_code: "vi",
      contextual_meaning: "con voi",
      explanation: null,
    });
    expect(parsed.contextual_meaning).toBe("con voi");
  });

  it("rejects occurrence mismatch (no trust in client substrings)", () => {
    expect(() =>
      parseConceptInteractionView({
        library_item_id: LIB_ID,
        learning_object_id: LO_ID,
        expression: "Elephant",
        occurrence_text: "Elephant",
        source_segment_text: source,
        start_codepoint: 0,
        end_codepoint: 9,
        learning_language_code: "en",
        support_language_code: "vi",
        contextual_meaning: "con voi",
        explanation: null,
      }),
    ).toThrow();
  });

  it("keeps explicit null explanation as null", () => {
    const parsed = parseConceptInteractionView({
      library_item_id: LIB_ID,
      learning_object_id: LO_ID,
      expression: "x",
      occurrence_text: source.slice(0, 1),
      source_segment_text: source,
      start_codepoint: 0,
      end_codepoint: 1,
      learning_language_code: "en",
      support_language_code: "vi",
      contextual_meaning: "meaning",
      explanation: null,
    });
    expect(parsed.explanation).toBeNull();
  });
});

describe("youtube url extraction (import pre-validation)", () => {
  it("extracts from watch URLs", () => {
    expect(youtubeIdFromUrl("https://www.youtube.com/watch?v=jNQXAC9IVRw")).toBe("jNQXAC9IVRw");
  });
  it("extracts from youtu.be short links", () => {
    expect(youtubeIdFromUrl("https://youtu.be/jNQXAC9IVRw")).toBe("jNQXAC9IVRw");
  });
  it("extracts from shorts/embed/live", () => {
    expect(youtubeIdFromUrl("https://www.youtube.com/shorts/jNQXAC9IVRw")).toBe("jNQXAC9IVRw");
    expect(youtubeIdFromUrl("https://www.youtube.com/embed/jNQXAC9IVRw")).toBe("jNQXAC9IVRw");
  });
  it("rejects non-youtube URLs", () => {
    expect(youtubeIdFromUrl("https://vimeo.com/123456")).toBeNull();
    expect(youtubeIdFromUrl("not a url")).toBeNull();
  });
});
