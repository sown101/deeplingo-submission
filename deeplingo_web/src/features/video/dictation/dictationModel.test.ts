import { describe, expect, it } from "vitest";
import {
  correctCount,
  diffAnswer,
  dictationTokens,
  isPerfect,
  lengthHint,
  shuffledTokens,
} from "./dictationModel";

describe("dictation model", () => {
  it("tokenizes words without punctuation, and Chinese per character", () => {
    expect(dictationTokens("I'm fine, thanks!", false)).toEqual(["I'm", "fine", "thanks"]);
    expect(dictationTokens("我很好，谢谢！", true)).toEqual(["我", "很", "好", "谢", "谢"]);
  });

  it("shuffles deterministically and never returns the original order for two or more words", () => {
    const tokens = ["I", "like", "coffee"];
    expect(shuffledTokens(tokens, 7)).toEqual(shuffledTokens(tokens, 7));
    for (let seed = 1; seed < 50; seed++) {
      const shuffled = shuffledTokens(tokens, seed);
      expect([...shuffled].sort()).toEqual([...tokens].sort());
      expect(shuffled).not.toEqual(tokens);
    }
    expect(shuffledTokens(["hi"], 3)).toEqual(["hi"]);
  });

  it("hints the number of words and the letters in each", () => {
    expect(lengthHint(["I", "like", "tea"], false)).toEqual(["_", "_ _ _ _", "_ _ _"]);
    expect(lengthHint(["我", "很", "好"], true)).toEqual(["□", "□", "□"]);
  });

  it("diffs answers word by word, ignoring case and curly apostrophes", () => {
    const expected = ["I'm", "very", "well", "thank", "you"];
    expect(isPerfect(diffAnswer(expected, ["i’m", "very", "well", "thank", "you"]))).toBe(true);
    const items = diffAnswer(expected, ["I'm", "well", "thanks", "you", "Georgie"]);
    expect(items.map((item) => item.kind)).toEqual(["correct", "missing", "correct", "wrong", "correct", "extra"]);
    expect(correctCount(items)).toBe(3);
    expect(diffAnswer(["a"], []).map((item) => item.kind)).toEqual(["missing"]);
    expect(isPerfect(diffAnswer([], []))).toBe(false);
  });

  // Owner report 2026-11-14: "I was taking it too personally" typed for this sentence showed "1 of 6 words right".
  // Graded against its own sentence the answer is perfect: the 1 of 6 came from grading it against a neighbouring
  // sentence, which the offset clip had played (see clipTiming).
  it("grades a typed answer without the final full stop as perfect", () => {
    const expected = dictationTokens("I was taking it too personally.", false);
    const answered = dictationTokens("I was taking it too personally", false);
    expect(expected).toHaveLength(6);
    expect(isPerfect(diffAnswer(expected, answered))).toBe(true);
    expect(correctCount(diffAnswer(expected, dictationTokens("i WAS taking it, too personally!", false)))).toBe(6);
    const neighbour = diffAnswer(dictationTokens("So what did you say to her?", false), answered);
    expect(correctCount(neighbour)).toBeLessThan(2);
  });

  it("grades Chinese per character, ignoring full-width punctuation and spaces", () => {
    const expected = dictationTokens("我太把它当回事了。", true);
    expect(expected).toHaveLength(8);
    expect(isPerfect(diffAnswer(expected, dictationTokens("我太把它当回事了", true)))).toBe(true);
    expect(isPerfect(diffAnswer(expected, dictationTokens("我 太把它 当回事了！", true)))).toBe(true);
    const items = diffAnswer(expected, dictationTokens("我太把他当回事了", true));
    expect(correctCount(items)).toBe(7);
    expect(items.filter((item) => item.kind === "wrong")).toEqual([{ kind: "wrong", expected: "它", answered: "他" }]);
  });
});
