import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TranscriptText } from "./TranscriptText";
import type { LearningObjectOccurrenceView } from "../../lib/api/dto";

const LO_1 = "11111111-1111-1111-1111-111111111111";
const LO_2 = "22222222-2222-2222-2222-222222222222";

describe("TranscriptText occurrence rendering", () => {
  it("renders plain text without recognizers when no occurrences exist", () => {
    render(<TranscriptText text="Plain text" occurrences={[]} onOccurrenceTap={vi.fn()} />);
    expect(screen.getByText("Plain text")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("passes EVERY covering learning object id on tap (no silent selection)", async () => {
    const onOccurrenceTap = vi.fn();
    const text = "new bank loan";
    const occurrences: LearningObjectOccurrenceView[] = [
      { learning_object_id: LO_1, start_codepoint: 4, end_codepoint: 8 },
      { learning_object_id: LO_2, start_codepoint: 4, end_codepoint: 13 },
    ];
    render(<TranscriptText text={text} occurrences={occurrences} onOccurrenceTap={onOccurrenceTap} />);
    await userEvent.click(screen.getAllByRole("button")[0]);
    expect(onOccurrenceTap).toHaveBeenCalledWith([LO_1, LO_2]);
  });

  it("keeps non-occurrence text non-interactive and row-tap compatible", async () => {
    const onOccurrenceTap = vi.fn();
    const text = "I put it off today";
    render(
      <TranscriptText
        text={text}
        occurrences={[{ learning_object_id: LO_1, start_codepoint: 2, end_codepoint: 12 }]}
        onOccurrenceTap={onOccurrenceTap}
      />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0].textContent).toBe("put it off");
    await userEvent.click(buttons[0]);
    expect(onOccurrenceTap).toHaveBeenCalledWith([LO_1]);
  });

  it("slices astral occurrences without splitting code points", async () => {
    const onOccurrenceTap = vi.fn();
    const text = "😀😀 hi";
    render(
      <TranscriptText
        text={text}
        occurrences={[{ learning_object_id: LO_1, start_codepoint: 0, end_codepoint: 1 }]}
        onOccurrenceTap={onOccurrenceTap}
      />,
    );
    const button = screen.getByRole("button");
    expect(button.textContent).toBe("😀");
    await userEvent.click(button);
    expect(onOccurrenceTap).toHaveBeenCalledWith([LO_1]);
  });
});

describe("TranscriptText word lookup", () => {
  it("gives the code-point span of any tapped word, after astral characters too", async () => {
    const onWordTap = vi.fn();
    const onOccurrenceTap = vi.fn();
    const text = "😀 I gave up.";
    const occurrences: LearningObjectOccurrenceView[] = [{ learning_object_id: LO_1, start_codepoint: 2, end_codepoint: 3 }];
    render(<TranscriptText text={text} occurrences={occurrences} onOccurrenceTap={onOccurrenceTap} onWordTap={onWordTap} />);
    await userEvent.click(screen.getByText("up"));
    expect(onWordTap).toHaveBeenCalledWith({ start: 9, end: 11 });
    await userEvent.click(screen.getByText("gave"));
    expect(onWordTap).toHaveBeenLastCalledWith({ start: 4, end: 8 });
    await userEvent.click(screen.getByRole("button", { name: "I" }));
    expect(onOccurrenceTap).toHaveBeenCalledWith([LO_1]);
    expect(onWordTap).toHaveBeenCalledTimes(2);
  });

  it("makes every Chinese character tappable on its own", async () => {
    const onWordTap = vi.fn();
    render(<TranscriptText text="我起床。" occurrences={[]} unspaced onOccurrenceTap={vi.fn()} onWordTap={onWordTap} />);
    await userEvent.click(screen.getByText("床"));
    expect(onWordTap).toHaveBeenCalledWith({ start: 2, end: 3 });
    expect(screen.getByText("。")).not.toHaveClass("word");
  });

  it("maps a text selection back to code points", async () => {
    const { selectionSpan } = await import("./TranscriptText");
    const { container } = render(
      <TranscriptText text="😀 I gave up." occurrences={[]} onOccurrenceTap={vi.fn()} onWordTap={vi.fn()} />,
    );
    const gave = screen.getByText("gave").firstChild as Text;
    const up = screen.getByText("up").firstChild as Text;
    const range = document.createRange();
    range.setStart(gave, 1);
    range.setEnd(up, 1);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    expect(selectionSpan(container as HTMLElement)).toEqual({ start: 5, end: 10 });
    selection.removeAllRanges();
    expect(selectionSpan(container as HTMLElement)).toBeNull();
  });
});
