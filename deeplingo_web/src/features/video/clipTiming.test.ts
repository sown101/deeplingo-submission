import { describe, expect, it } from "vitest";
import { CLIP_PADDING, clipStep, clipWindow } from "./clipTiming";

describe("clipWindow", () => {
  it("pads the sentence on both sides", () => {
    expect(clipWindow(10_000, 12_500)).toEqual({
      startMs: 10_000 - CLIP_PADDING.leadMs,
      endMs: 12_500 + CLIP_PADDING.tailMs,
    });
  });

  it("never starts before the video and takes other padding", () => {
    expect(clipWindow(50, 900, { leadMs: 300, tailMs: 0 })).toEqual({ startMs: 0, endMs: 900 });
    expect(clipWindow(1_000.4, 1_999.6, { leadMs: 0, tailMs: 0 })).toEqual({ startMs: 1_000, endMs: 2_000 });
  });

  it("keeps a broken sentence playable", () => {
    expect(clipWindow(5_000, 4_000, { leadMs: 0, tailMs: 0 })).toEqual({ startMs: 5_000, endMs: 5_001 });
  });
});

describe("clipStep", () => {
  const clip = { startMs: 9_850, endMs: 12_700 };

  it("ignores the old position the player still reports right after the seek", () => {
    // "Listen again": the player paused at the clip end and reports it once more before seeking.
    expect(clipStep(clip, false, 12_710, 1)).toEqual({ armed: false, action: { kind: "ignore" } });
    // "Previous": the player was far after this sentence.
    expect(clipStep(clip, false, 30_000, 1).action).toEqual({ kind: "ignore" });
    // A sentence far before.
    expect(clipStep(clip, false, 2_000, 1).action).toEqual({ kind: "ignore" });
  });

  it("arms on the first position from after the seek and stops on a timer, not on the next report", () => {
    expect(clipStep(clip, false, 9_900, 1)).toEqual({ armed: true, action: { kind: "stopIn", ms: 2_800 } });
    // A seek may land a little before the target.
    expect(clipStep(clip, false, 9_400, 1).armed).toBe(true);
  });

  it("scales the timer by the playback rate", () => {
    expect(clipStep(clip, true, 11_700, 0.5).action).toEqual({ kind: "stopIn", ms: 2_000 });
    expect(clipStep(clip, true, 11_700, 1.25).action).toEqual({ kind: "stopIn", ms: 800 });
    expect(clipStep(clip, true, 11_700, 0).action).toEqual({ kind: "stopIn", ms: 1_000 });
  });

  it("stops at once when an armed clip is already past its end", () => {
    expect(clipStep(clip, true, 12_700, 1)).toEqual({ armed: true, action: { kind: "stop" } });
    expect(clipStep(clip, true, 13_400, 1).action).toEqual({ kind: "stop" });
  });
});
