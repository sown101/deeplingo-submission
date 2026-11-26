import { useEffect, useMemo, useRef, useState } from "react";
import { partitionText } from "../../lib/unicode/codePoints";
import type { LearningObjectOccurrenceView } from "../../lib/api/dto";

const WORD = /[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu;

export interface CodePointSpan {
  start: number;
  end: number;
}

// Renders segment text with trusted occurrence emphasis. Boundaries are
// Unicode CODE POINT indexes converted to UTF-16 offsets; overlapping
// occurrences are never silently collapsed — a tap on a piece covered by
// multiple occurrences receives every covering LearningObject ID.
//
// Every other word (every character in unspaced languages such as Chinese) is
// tappable for a lookup. Each rendered run carries its code-point start in
// `data-cp` so a text selection can be mapped back to code points.
export function TranscriptText({
  text,
  occurrences,
  unspaced = false,
  onOccurrenceTap,
  onWordTap,
}: {
  text: string;
  occurrences: LearningObjectOccurrenceView[];
  unspaced?: boolean;
  onOccurrenceTap: (learningObjectIds: string[]) => void;
  onWordTap?: (span: CodePointSpan) => void;
}) {
  const anchor = useRef<CodePointSpan | null>(null);
  const [selected, setSelected] = useState<CodePointSpan | null>(null);
  useEffect(() => { anchor.current = null; setSelected(null); }, [text]);
  function tap(span: CodePointSpan, extend = false) {
    if (extend && anchor.current) {
      const range = { start: Math.min(anchor.current.start, span.start), end: Math.max(anchor.current.end, span.end) };
      anchor.current = null; setSelected(range); onWordTap?.(range);
    } else if (extend) { anchor.current = span; setSelected(span); }
    else { anchor.current = span; setSelected(null); onWordTap?.(span); }
  }
  const pieces = useMemo(
    () =>
      partitionText(
        text,
        occurrences.map((o) => ({
          start: o.start_codepoint,
          end: o.end_codepoint,
          value: o.learning_object_id,
        })),
      ),
    [text, occurrences],
  );

  return (
    <p className="segment-text" data-segment-text="">
      {pieces.map((piece, index) =>
        piece.covering.length === 0 ? (
          <PlainRun key={index} text={piece.text} start={piece.startCodepoint} unspaced={unspaced} onWordTap={onWordTap ? tap : undefined} selected={selected} />
        ) : (
          <span
            key={index}
            className="occurrence"
            role="button"
            tabIndex={0}
            data-cp={piece.startCodepoint}
            data-range-selected={selected !== null && piece.startCodepoint >= selected.start && piece.startCodepoint + [...piece.text].length <= selected.end}
            onMouseDown={e => { if (e.shiftKey) e.preventDefault(); }}
            onClick={(e) => {
              if (hasSelection() && !e.shiftKey) return;
              e.stopPropagation();
              const span = { start: piece.startCodepoint, end: piece.startCodepoint + [...piece.text].length };
              if (e.shiftKey && onWordTap) { tap(span, true); return; }
              anchor.current = span; setSelected(null);
              onOccurrenceTap(piece.covering);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                if (e.shiftKey && onWordTap) { tap({ start: piece.startCodepoint, end: piece.startCodepoint + [...piece.text].length }, true); return; }
                onOccurrenceTap(piece.covering);
              }
            }}
          >
            {piece.text}
          </span>
        ),
      )}
    </p>
  );
}

function PlainRun({
  text,
  start,
  unspaced,
  onWordTap,
  selected,
}: {
  text: string;
  start: number;
  unspaced: boolean;
  onWordTap?: (span: CodePointSpan, extend?: boolean) => void;
  selected?: CodePointSpan | null;
}) {
  if (!onWordTap) return <span data-cp={start}>{text}</span>;
  const parts: { text: string; start: number; word: boolean }[] = [];
  const chars = [...text];
  if (unspaced) {
    chars.forEach((ch, i) => parts.push({ text: ch, start: start + i, word: /[\p{L}\p{N}]/u.test(ch) }));
  } else {
    let cursor = 0; // UTF-16 offset in `text`
    let cp = start;
    for (const match of text.matchAll(WORD)) {
      const index = match.index ?? 0;
      if (index > cursor) {
        const gap = text.slice(cursor, index);
        parts.push({ text: gap, start: cp, word: false });
        cp += [...gap].length;
      }
      parts.push({ text: match[0], start: cp, word: true });
      cp += [...match[0]].length;
      cursor = index + match[0].length;
    }
    if (cursor < text.length) parts.push({ text: text.slice(cursor), start: cp, word: false });
  }
  return (
    <>
      {parts.map((part, i) =>
        part.word ? (
          <span
            key={i}
            className="word"
            data-cp={part.start}
            role="button"
            tabIndex={0}
            data-range-selected={selected != null && part.start >= selected.start && part.start + [...part.text].length <= selected.end}
            onMouseDown={e => { if (e.shiftKey) e.preventDefault(); }}
            onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onWordTap({ start: part.start, end: part.start + [...part.text].length }, e.shiftKey); } }}
            onClick={(e) => {
              if (hasSelection() && !e.shiftKey) return;
              e.stopPropagation();
              onWordTap({ start: part.start, end: part.start + [...part.text].length }, e.shiftKey);
            }}
          >
            {part.text}
          </span>
        ) : (
          <span key={i} data-cp={part.start}>
            {part.text}
          </span>
        ),
      )}
    </>
  );
}

function hasSelection(): boolean {
  const selection = window.getSelection();
  return selection !== null && !selection.isCollapsed && selection.toString().trim().length > 0;
}

// Maps the current text selection inside `container` to code points, or null when the
// selection is empty or leaves the segment text.
export function selectionSpan(container: HTMLElement): CodePointSpan | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0 || !selection.toString().trim()) return null;
  const range = selection.getRangeAt(0);
  const start = pointToCodePoint(container, range.startContainer, range.startOffset);
  const end = pointToCodePoint(container, range.endContainer, range.endOffset);
  if (start === null || end === null || end <= start) return null;
  return { start, end };
}

function pointToCodePoint(container: HTMLElement, node: Node, offset: number): number | null {
  if (!container.contains(node)) return null;
  const prefix = document.createRange();
  prefix.selectNodeContents(container);
  prefix.setEnd(node, offset);
  return [...prefix.toString()].length;
}
