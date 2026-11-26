// Sentence-by-sentence dictation on the watch page (local practice, like the legacy
// mobile UX). Pure helpers: tokens, shuffled chips, the length hint and a word diff.
// The comparison is presentation only: nothing is submitted, graded by the server or
// recorded as Evidence, so it never changes mastery or review.

const WORD = /[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu;
const LETTER = /[\p{L}\p{N}]/u;

export type DictationLevel = "easy" | "hard";

/** Words to write: whole words, or single characters in unspaced languages. */
export function dictationTokens(text: string, unspaced: boolean): string[] {
  if (unspaced) return [...text].filter((ch) => LETTER.test(ch));
  return [...text.matchAll(WORD)].map((match) => match[0]);
}

/** Tokens in a different order (deterministic for a seed, never the original order when avoidable). */
export function shuffledTokens(tokens: string[], seed: number): string[] {
  const result = [...tokens];
  let state = (seed >>> 0) || 1;
  const next = () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 0x100000000;
  };
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  if (result.length > 1 && result.every((token, i) => token === tokens[i])) {
    result.push(result.shift()!);
  }
  return result;
}

/** Length hint: one group of underscores per word ("_ _ _ _"), or one box per character. */
export function lengthHint(tokens: string[], unspaced: boolean): string[] {
  if (unspaced) return tokens.map(() => "□");
  return tokens.map((token) => Array.from({ length: [...token].length }, () => "_").join(" "));
}

export function normalizeToken(token: string): string {
  return token.normalize("NFKC").toLocaleLowerCase().replace(/’/g, "'");
}

export type DiffKind = "correct" | "wrong" | "missing" | "extra";

export interface DiffItem {
  kind: DiffKind;
  expected?: string;
  answered?: string;
}

/**
 * Word-level alignment of the answer to the sentence (case and punctuation ignored).
 * Matches come from a longest common subsequence; a wrong word next to a missing one is
 * shown as one "wrong" item.
 */
export function diffAnswer(expected: string[], answered: string[]): DiffItem[] {
  const a = expected.map(normalizeToken);
  const b = answered.map(normalizeToken);
  const table = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const items: DiffItem[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      items.push({ kind: "correct", expected: expected[i], answered: answered[j] });
      i++;
      j++;
    } else if (i < a.length && j < b.length && table[i + 1][j + 1] === table[i][j]) {
      items.push({ kind: "wrong", expected: expected[i], answered: answered[j] });
      i++;
      j++;
    } else if (j < b.length && (i >= a.length || table[i][j + 1] >= table[i + 1][j])) {
      items.push({ kind: "extra", answered: answered[j] });
      j++;
    } else {
      items.push({ kind: "missing", expected: expected[i] });
      i++;
    }
  }
  return items;
}

export function isPerfect(items: DiffItem[]): boolean {
  return items.length > 0 && items.every((item) => item.kind === "correct");
}

export function correctCount(items: DiffItem[]): number {
  return items.filter((item) => item.kind === "correct").length;
}
