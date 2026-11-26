import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TranscriptText, selectionSpan } from "./TranscriptText";

afterEach(() => window.getSelection()?.removeAllRanges());

it("looks up a highlighted phrase without Shift when the selection ends at element boundaries", () => {
  const { container } = render(<TranscriptText text="😀 book a room" occurrences={[]} onOccurrenceTap={vi.fn()} onWordTap={vi.fn()} />);
  const range = document.createRange();
  range.setStart(screen.getByText("book"), 0);
  range.setEnd(screen.getByText("room"), 1);
  window.getSelection()!.addRange(range);
  expect(selectionSpan(container)).toEqual({ start: 2, end: 13 });
});

it("maps a whole highlighted Chinese sentence including emoji from paragraph boundaries", () => {
  const { container } = render(<TranscriptText text="😀我想订房" unspaced occurrences={[]} onOccurrenceTap={vi.fn()} onWordTap={vi.fn()} />);
  const range = document.createRange();
  range.selectNodeContents(container.querySelector("p")!);
  window.getSelection()!.addRange(range);
  expect(selectionSpan(container)).toEqual({ start: 0, end: 5 });
});

it("does not submit a whitespace-only highlighted range for a word lookup", () => {
  const { container } = render(<TranscriptText text="book   room" occurrences={[]} onOccurrenceTap={vi.fn()} onWordTap={vi.fn()} />);
  const range = document.createRange();
  const gap = container.querySelector('[data-cp="4"]')!;
  range.selectNodeContents(gap);
  window.getSelection()!.addRange(range);
  expect(selectionSpan(container)).toBeNull();
});

it("Shift-click selects a phrase in either direction using Unicode code points", () => {
  const lookup = vi.fn();
  render(<TranscriptText text="😀 book a room" occurrences={[]} onOccurrenceTap={vi.fn()} onWordTap={lookup} />);
  fireEvent.click(screen.getByText("room"), { shiftKey: true });
  expect(lookup).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("book"), { shiftKey: true });
  expect(lookup).toHaveBeenCalledTimes(1);
  expect(lookup).toHaveBeenCalledWith({ start: 2, end: 13 });
});

it("preserves Chinese character spans and normal single-word lookup", () => {
  const lookup = vi.fn();
  render(<TranscriptText text="😀我想订房" unspaced occurrences={[]} onOccurrenceTap={vi.fn()} onWordTap={lookup} />);
  fireEvent.click(screen.getByText("订"), { shiftKey: true });
  fireEvent.click(screen.getByText("房"), { shiftKey: true });
  expect(lookup).toHaveBeenLastCalledWith({ start: 3, end: 5 });
  fireEvent.click(screen.getByText("我"));
  expect(lookup).toHaveBeenLastCalledWith({ start: 1, end: 2 });
});
