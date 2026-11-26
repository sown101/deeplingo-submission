import { describe, expect, it } from "vitest";
import {
  buildUtf16OffsetTable,
  codePointLength,
  convertSpan,
  partitionText,
  sliceByCodePoints,
} from "../../lib/unicode/codePoints";

// Mirrors backend fixture semantics: composed café, decomposed e\u0301,
// Japanese, ZWJ emoji. Backend offsets are Unicode CODE POINTS; JS indexes
// UTF-16 code units. Raw JS substring indexing must never be used.
describe("code point -> UTF-16 conversion", () => {
  it("counts code points for composed cafe", () => {
    const text = "café";
    expect(codePointLength(text)).toBe(4);
    expect(text.length).toBe(4);
    expect(sliceByCodePoints(text, { startCodepoint: 3, endCodepoint: 4 })).toBe("é");
  });

  it("handles decomposed accents (combining marks are separate code points)", () => {
    const text = "cafe\u0301"; // e + combining acute
    expect(codePointLength(text)).toBe(5);
    expect(text.length).toBe(5);
    // Slice of the accented character is TWO code points: e + combining mark
    expect(sliceByCodePoints(text, { startCodepoint: 3, endCodepoint: 5 })).toBe("e\u0301");
    expect(sliceByCodePoints(text, { startCodepoint: 3, endCodepoint: 4 })).toBe("e");
  });

  it("maps astral emoji with surrogate pairs", () => {
    const text = "a😀b"; // a, surrogate pair, b -> 3 code points, 4 UTF-16 units
    expect(codePointLength(text)).toBe(3);
    expect(text.length).toBe(4);
    const table = buildUtf16OffsetTable(text).offsetTable;
    expect(table).toEqual([0, 1, 3, 4]);
    expect(sliceByCodePoints(text, { startCodepoint: 1, endCodepoint: 2 })).toBe("😀");
    expect(sliceByCodePoints(text, { startCodepoint: 2, endCodepoint: 3 })).toBe("b");
  });

  it("handles Japanese characters", () => {
    const text = "こんにちは";
    expect(codePointLength(text)).toBe(5);
    expect(sliceByCodePoints(text, { startCodepoint: 0, endCodepoint: 2 })).toBe("こん");
  });

  it("handles ZWJ emoji family", () => {
    const text = "👩‍👩‍👧‍👦x"; // family ZWJ sequence: many code points, then x
    expect(sliceByCodePoints(text, { startCodepoint: codePointLength(text) - 1, endCodepoint: codePointLength(text) })).toBe("x");
    expect(sliceByCodePoints(text, { startCodepoint: 0, endCodepoint: 1 })).toBe("👩");
  });

  it("rejects invalid spans", () => {
    const text = "abc";
    expect(convertSpan(text, { startCodepoint: -1, endCodepoint: 1 })).toBeNull();
    expect(convertSpan(text, { startCodepoint: 2, endCodepoint: 2 })).toBeNull();
    expect(convertSpan(text, { startCodepoint: 0, endCodepoint: 9 })).toBeNull();
    expect(sliceByCodePoints(text, { startCodepoint: 1, endCodepoint: 0 })).toBeNull();
  });

  it("does not split a code point even when it splits a grapheme", () => {
    const text = "e\u0301x";
    // Span [1,2) is the combining mark alone: allowed as code points, must
    // return exactly the combining mark, never half a surrogate.
    expect(sliceByCodePoints(text, { startCodepoint: 1, endCodepoint: 2 })).toBe("\u0301");
  });
});

describe("occurrence partition (overlap policy)", () => {
  it("partitions plain text with no occurrences", () => {
    const pieces = partitionText("hello", []);
    expect(pieces).toHaveLength(1);
    expect(pieces[0].text).toBe("hello");
    expect(pieces[0].covering).toHaveLength(0);
  });

  it("isolates a single occurrence", () => {
    const text = "I put it off today";
    // "put it off" = code points [2, 12)
    const pieces = partitionText(text, [
      { start: 2, end: 12, value: "lo-id-1" },
    ]);
    expect(pieces.map((p) => p.text).join("")).toBe(text);
    const emphasized = pieces.filter((p) => p.covering.length > 0);
    expect(emphasized).toHaveLength(1);
    expect(emphasized[0].text).toBe("put it off");
    expect(emphasized[0].covering).toEqual(["lo-id-1"]);
  });

  it("keeps every overlapping occurrence instead of choosing one silently", () => {
    // "new bank loan" with overlapping spans "bank" [4,8) and "bank loan" [4,13)
    const text = "new bank loan";
    const pieces = partitionText(text, [
      { start: 4, end: 8, value: "lo-bank" },
      { start: 4, end: 13, value: "lo-bank-loan" },
    ]);
    const covered = pieces.find((p) => p.text === "bank");
    expect(covered?.covering.sort()).toEqual(["lo-bank", "lo-bank-loan"]);
    expect(pieces.map((p) => p.text).join("")).toBe(text);
  });

  it("keeps nested occurrences individually addressable", () => {
    const text = "abcdef";
    const pieces = partitionText(text, [
      { start: 0, end: 6, value: "outer" },
      { start: 2, end: 4, value: "inner" },
    ]);
    expect(pieces.map((p) => p.text).join("")).toBe(text);
    const inner = pieces.find((p) => p.text === "cd");
    expect(inner?.covering).toEqual(["outer", "inner"]);
    const head = pieces.find((p) => p.text === "ab");
    expect(head?.covering).toEqual(["outer"]);
  });

  it("ignores out-of-range intervals", () => {
    const pieces = partitionText("abc", [{ start: 0, end: 9, value: "bad" }]);
    expect(pieces.every((p) => p.covering.length === 0)).toBe(true);
  });

  it("slices occurrences across astral boundaries correctly", () => {
    const text = "😀😀 bright day";
    // First emoji occupies code points [0,1)
    const pieces = partitionText(text, [{ start: 0, end: 1, value: "emoji" }]);
    expect(pieces[0].text).toBe("😀");
    expect(pieces[0].covering).toEqual(["emoji"]);
  });
});
