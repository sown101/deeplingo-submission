import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DictationPanel } from "./DictationPanel";
import type { TranscriptSegmentView } from "../../../lib/api/dto";

function segment(i: number, text: string): TranscriptSegmentView {
  return {
    segment_id: `0000000${i}-0000-0000-0000-000000000000`,
    sequence: i,
    text,
    start_ms: i * 1000,
    end_ms: i * 1000 + 900,
    translation: { language_code: "vi", text: `dịch ${i}` },
    romanizations: [],
    learning_objects: [],
  };
}

function fakePlayer() {
  const ends: Array<() => void> = [];
  return {
    ends,
    playClip: vi.fn((_start: number, _end: number, onEnd?: () => void) => {
      if (onEnd) ends.push(onEnd);
    }),
    pause: vi.fn(),
    setRate: vi.fn(),
    finish() {
      act(() => {
        ends.shift()?.();
      });
    },
  };
}

const SEGMENTS = [segment(1, "I like tea."), segment(2, "Thank you!")];

describe("DictationPanel practice log (M1 S4)", () => {
  it("reports each checked answer with selectors and the raw answer, never a score", () => {
    const player = fakePlayer();
    const onChecked = vi.fn();
    render(<DictationPanel segments={SEGMENTS} languageCode="en" unspaced={false} startIndex={0} player={player}
      onChecked={onChecked} />);
    fireEvent.click(screen.getByRole("button", { name: "Hard · type it" }));
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    player.finish();
    fireEvent.click(screen.getByRole("button", { name: "Show hint" }));
    fireEvent.change(screen.getByLabelText("Type what you hear"), { target: { value: "I like tee" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(onChecked).toHaveBeenCalledWith({
      segment_id: SEGMENTS[0].segment_id, level: "hard", answer: "I like tee", hint_shown: true,
    });
  });

  it("reports an arranged answer as its words", () => {
    const player = fakePlayer();
    const onChecked = vi.fn();
    render(<DictationPanel segments={SEGMENTS} languageCode="en" unspaced={false} startIndex={0} player={player}
      onChecked={onChecked} />);
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    player.finish();
    const pool = screen.getByLabelText("Words");
    for (const word of ["I", "like"]) {
      fireEvent.click(Array.from(pool.querySelectorAll("button")).find((b) => b.textContent === word)!);
    }
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(onChecked).toHaveBeenCalledWith(expect.objectContaining({ level: "easy", answer: "I like", hint_shown: false }));
  });
});

describe("DictationPanel", () => {
  it("plays each sentence, lets the learner arrange words and shows a word diff", () => {
    const player = fakePlayer();
    render(<DictationPanel segments={SEGMENTS} languageCode="en" unspaced={false} startIndex={0} player={player} />);
    fireEvent.click(screen.getByRole("button", { name: "0.75×" }));
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    expect(player.setRate).toHaveBeenCalledWith(0.75);
    expect(player.playClip).toHaveBeenCalledWith(1000, 1900, expect.any(Function));
    expect(screen.getByRole("button", { name: "Listening…" })).toBeDisabled();
    player.finish();
    expect(screen.getByRole("button", { name: "Listen again" })).toBeEnabled();

    const pool = screen.getByLabelText("Words");
    for (const word of ["I", "tea", "like"]) {
      fireEvent.click(Array.from(pool.querySelectorAll("button")).find((b) => b.textContent === word)!);
    }
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(screen.getByText("2 of 3 words right")).toBeInTheDocument();
    expect(screen.getByText("dịch 1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next sentence" }));
    expect(player.playClip).toHaveBeenLastCalledWith(2000, 2900, expect.any(Function));
  });

  it("hard mode types the sentence, hints its length and repeats the clip", () => {
    vi.useFakeTimers();
    const player = fakePlayer();
    render(<DictationPanel segments={SEGMENTS} languageCode="en" unspaced={false} startIndex={1} player={player} />);
    fireEvent.click(screen.getByRole("button", { name: "Hard · type it" }));
    fireEvent.click(screen.getByRole("button", { name: "2 times" }));
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    player.finish();
    act(() => {
      vi.advanceTimersByTime(400);
    });
    vi.useRealTimers();
    expect(player.playClip).toHaveBeenCalledTimes(2);
    player.finish();

    fireEvent.click(screen.getByRole("button", { name: "Show hint" }));
    const groups = screen.getByLabelText("2 words").querySelectorAll(".hint-word");
    expect(Array.from(groups).map((group) => group.textContent)).toEqual(["_ _ _ _ _", "_ _ _"]);
    fireEvent.change(screen.getByLabelText("Type what you hear"), { target: { value: "thank you" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(screen.getByText("Perfect!")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(screen.getByText(/1 of 1 sentences perfect · 100% of words right/)).toBeInTheDocument();
  });

  it("writes Chinese per character and pauses the player when it closes", () => {
    const player = fakePlayer();
    const view = render(
      <DictationPanel segments={[segment(1, "我很好。")]} languageCode="zh" unspaced startIndex={0} player={player} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    player.finish();
    expect(screen.getByLabelText("Words").querySelectorAll("button")).toHaveLength(3);
    view.unmount();
    expect(player.pause).toHaveBeenCalled();
  });
});

describe("DictationPanel typed answers", () => {
  function typeAndCheck(text: string, sentence: string, unspaced: boolean, enter: { isComposing?: boolean } = {}) {
    const player = fakePlayer();
    render(<DictationPanel segments={[segment(1, sentence)]} languageCode={unspaced ? "zh" : "en"} unspaced={unspaced}
      startIndex={0} player={player} />);
    fireEvent.click(screen.getByRole("button", { name: "Hard · type it" }));
    fireEvent.click(screen.getByRole("button", { name: "Start dictation" }));
    player.finish();
    const box = screen.getByLabelText("Type what you hear");
    fireEvent.change(box, { target: { value: text } });
    fireEvent.keyDown(box, { key: "Enter", ...enter });
  }

  it("marks the owner's exact answer perfect", () => {
    typeAndCheck("I was taking it too personally", "I was taking it too personally.", false);
    expect(screen.getByText("Perfect!")).toBeInTheDocument();
  });

  it("counts right words in the score line", () => {
    typeAndCheck("I was making it so personal", "I was taking it too personally.", false);
    expect(screen.getByText("3 of 6 words right")).toBeInTheDocument();
  });

  it("does not check on the Enter that ends an IME composition", () => {
    typeAndCheck("wo tai", "我太把它当回事了。", true, { isComposing: true });
    expect(screen.queryByRole("button", { name: "Check" })).toBeInTheDocument();
    expect(screen.queryByText(/characters right/)).not.toBeInTheDocument();
  });

  it("grades a Chinese answer per character", () => {
    typeAndCheck("我太把他当回事了", "我太把它当回事了。", true);
    expect(screen.getByText("7 of 8 characters right")).toBeInTheDocument();
  });
});
