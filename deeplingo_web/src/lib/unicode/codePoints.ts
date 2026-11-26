// Unicode CODE POINT -> UTF-16 code unit conversion.
//
// Backend occurrence offsets are zero-based Unicode CODE POINT indices into
// the unnormalized segment text with an exclusive end. JavaScript strings
// index UTF-16 code units. This module converts code-point boundaries to
// UTF-16 offsets so spans never use raw JS substring indexes.

export interface Utf16OffsetTable {
  // offsetTable[i] = UTF-16 offset of code point i; length = codePointCount + 1
  offsetTable: number[];
  codePointCount: number;
}

export function buildUtf16OffsetTable(text: string): Utf16OffsetTable {
  const offsetTable: number[] = [0];
  let utf16 = 0;
  for (const ch of text) {
    // The string iterator yields one code point per iteration; a code point
    // outside the BMP occupies two UTF-16 code units.
    utf16 += ch.length;
    offsetTable.push(utf16);
  }
  return { offsetTable, codePointCount: offsetTable.length - 1 };
}

export interface OccurrenceSpan {
  startCodepoint: number;
  endCodepoint: number;
}

export interface ConvertedSpan {
  startUtf16: number;
  endUtf16: number;
}

export function convertSpan(text: string, span: OccurrenceSpan): ConvertedSpan | null {
  const { offsetTable, codePointCount } = buildUtf16OffsetTable(text);
  const { startCodepoint, endCodepoint } = span;
  if (
    !Number.isInteger(startCodepoint) ||
    !Number.isInteger(endCodepoint) ||
    startCodepoint < 0 ||
    endCodepoint <= startCodepoint ||
    endCodepoint > codePointCount
  ) {
    return null;
  }
  return { startUtf16: offsetTable[startCodepoint], endUtf16: offsetTable[endCodepoint] };
}

export function sliceByCodePoints(text: string, span: OccurrenceSpan): string | null {
  const converted = convertSpan(text, span);
  if (!converted) return null;
  return text.slice(converted.startUtf16, converted.endUtf16);
}

export function codePointLength(text: string): number {
  return [...text].length;
}

export interface Interval<T> {
  start: number; // code point index, inclusive
  end: number; // code point index, exclusive
  value: T;
}

export interface PartitionPiece<T> {
  text: string;
  // Every interval covering this piece; empty when the piece is plain text.
  covering: T[];
  startCodepoint: number;
  endCodepoint: number;
}

// Partitions text into pieces at interval boundaries using code-point indexes.
// Each piece lists every covering interval so overlapping occurrences are
// never silently collapsed.
export function partitionText<T>(
  text: string,
  intervals: readonly Interval<T>[],
): PartitionPiece<T>[] {
  const codePointCount = codePointLength(text);
  const valid = intervals.filter(
    (i) =>
      Number.isInteger(i.start) &&
      Number.isInteger(i.end) &&
      i.start >= 0 &&
      i.end > i.start &&
      i.end <= codePointCount,
  );
  const boundaries = new Set<number>([0, codePointCount]);
  for (const interval of valid) {
    boundaries.add(interval.start);
    boundaries.add(interval.end);
  }
  const ordered = [...boundaries].sort((a, b) => a - b);
  const table = buildUtf16OffsetTable(text).offsetTable;
  const pieces: PartitionPiece<T>[] = [];
  for (let i = 0; i + 1 < ordered.length; i++) {
    const start = ordered[i];
    const end = ordered[i + 1];
    const covering = valid.filter((v) => v.start <= start && v.end >= end).map((v) => v.value);
    pieces.push({
      text: text.slice(table[start], table[end]),
      covering,
      startCodepoint: start,
      endCodepoint: end,
    });
  }
  return pieces;
}
