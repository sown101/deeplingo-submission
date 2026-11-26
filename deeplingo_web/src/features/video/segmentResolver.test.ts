import { describe, expect, it } from "vitest";
import { SegmentResolver } from "./segmentResolver";

interface Seg {
  sequence: number;
  start_ms: number;
  end_ms: number;
  label: string;
}

function seg(sequence: number, start: number, end: number, label: string): Seg {
  return { sequence, start_ms: start, end_ms: end, label };
}

describe("SegmentResolver", () => {
  it("returns null before first, in gaps, and at/after final end", () => {
    const resolver = new SegmentResolver([seg(1, 1000, 2000, "a"), seg(2, 3000, 4000, "b")]);
    expect(resolver.resolve(0)).toBeNull();
    expect(resolver.resolve(999)).toBeNull();
    expect(resolver.resolve(2500)).toBeNull();
    expect(resolver.resolve(4000)).toBeNull();
    expect(resolver.resolve(99999)).toBeNull();
  });

  it("uses half-open interval semantics [start, end)", () => {
    const resolver = new SegmentResolver([seg(1, 1000, 2000, "a")]);
    expect(resolver.resolve(1000)?.label).toBe("a");
    expect(resolver.resolve(1999)?.label).toBe("a");
    expect(resolver.resolve(2000)).toBeNull();
  });

  it("latest start wins on overlap and earlier resumes when shorter ends", () => {
    const a = seg(1, 0, 10000, "a");
    const b = seg(2, 3000, 5000, "b");
    const resolver = new SegmentResolver([a, b]);
    expect(resolver.resolve(1000)?.label).toBe("a");
    expect(resolver.resolve(3000)?.label).toBe("b");
    expect(resolver.resolve(4999)?.label).toBe("b");
    expect(resolver.resolve(5000)?.label).toBe("a");
    expect(resolver.resolve(10000)).toBeNull();
  });

  it("equal starts use highest sequence", () => {
    const first = seg(1, 1000, 5000, "first");
    const second = seg(2, 1000, 9000, "second");
    const resolver = new SegmentResolver([first, second]);
    expect(resolver.resolve(2000)?.label).toBe("second");
    // shorter high-sequence segment finishes and reveals earlier one
    expect(resolver.resolve(9000)).toBeNull();
  });

  it("complete tie keeps stable earlier list index", () => {
    const s1 = seg(7, 1000, 2000, "s1");
    const s2 = seg(7, 1000, 2000, "s2");
    const resolver = new SegmentResolver([s1, s2]);
    expect(resolver.resolve(1500)?.label).toBe("s1");
  });

  it("ignores invalid timing", () => {
    const resolver = new SegmentResolver([seg(1, 5000, 1000, "bad"), seg(2, 0, 1000, "good")]);
    expect(resolver.resolve(500)?.label).toBe("good");
    expect(resolver.resolve(3000)).toBeNull();
  });

  it("handles an arbitrary seek position", () => {
    const segments = [seg(1, 0, 1200, "one"), seg(2, 1200, 7974, "two"), seg(3, 7974, 18881, "three")];
    const resolver = new SegmentResolver(segments);
    expect(resolver.resolve(6000)?.label).toBe("two");
    expect(resolver.resolve(12000)?.label).toBe("three");
    expect(resolver.resolve(18881)).toBeNull();
  });
});
