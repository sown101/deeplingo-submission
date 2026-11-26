import type { ReviewCard, ServerType } from "../review/reviewModels";
import type { NotebookScope, StudyWord } from "./studyTypes";

// Choosing what a review asks and where the study screens live. Everything here is pure: the screens hold the state
// and the API calls.

/** The question types of the review settings. Multiple choice, Match pairs and Order count toward
 * the review schedule; Pronunciation and Writing are practice only (owner decision 2026-11-14). */
export type ReviewType = "choice" | "match" | "order" | "speak" | "write";
export const REVIEW_TYPES: readonly ReviewType[] = ["choice", "match", "order", "speak", "write"];
const SERVER_TYPES: Record<ReviewType, ServerType[]> = {
  choice: ["choice", "listening"], match: ["match"], order: ["order"], speak: ["pronunciation"], write: ["writing"],
};

export interface StudyDisplay {
  showAnswer: boolean;
  images: boolean;
  reading: boolean;
}

/** The server takes at most this many chosen words for one review. */
export const MAX_REVIEW_WORDS = 50;
const MAX_MATCH_PAIRS = 4;

/** Where a scope lives: a notebook id, "all" (the shelf) or "level-0" .. "level-4" of the shelf chart. */
export function scopeHref(scope: NotebookScope): string {
  if (scope === "all") return "/words/lists";
  const level = /^level-([0-4])$/.exec(scope);
  if (level) return `/words?level=${level[1]}`;
  return `/words/lists/${encodeURIComponent(scope)}`;
}

export const scopePath = (scope: NotebookScope, screen: "flashcards" | "writing") =>
  `/notebook/${encodeURIComponent(scope)}/${screen}`;

/** The review of one language's deck: exactly the chosen words, or the deck's due cards when none are named. */
export function reviewHref(language: string, conceptIds: string[], types: ReviewType[], display: StudyDisplay, back: string): string {
  const params = new URLSearchParams({ types: types.join(",") });
  if (conceptIds.length) params.set("concepts", conceptIds.slice(0, MAX_REVIEW_WORDS).join(","));
  if (!display.showAnswer) params.set("answer", "0");
  if (!display.images) params.set("images", "0");
  if (!display.reading) params.set("reading", "0");
  params.set("back", back);
  return `/review/${encodeURIComponent(language)}?${params}`;
}

/** What a review link asks for; with no types, Multiple choice. */
export function readReviewParams(params: URLSearchParams) {
  const types = (params.get("types") ?? "").split(",").filter((type): type is ReviewType => (REVIEW_TYPES as readonly string[]).includes(type));
  return {
    types: types.length ? [...new Set(types)] : (["choice"] as ReviewType[]),
    conceptIds: (params.get("concepts") ?? "").split(",").filter(Boolean).slice(0, MAX_REVIEW_WORDS),
    display: { showAnswer: params.get("answer") !== "0", images: params.get("images") !== "0", reading: params.get("reading") !== "0" },
    back: params.get("back") ?? "/words/lists",
  };
}

export const serverTypes = (types: ReviewType[]): ServerType[] => types.flatMap((type) => SERVER_TYPES[type]);

const HAN = /\p{Script=Han}/u;
/** The Han characters of a word (empty for any other script). */
export const hanziOf = (word: StudyWord) => [...word.text].filter((character) => HAN.test(character));
/** Only a Chinese or Japanese word made wholly of Han characters has writing practice. */
export const isHanWord = (word: StudyWord) => /^(zh|ja)\b/.test(word.languageCode) && hanziOf(word).length > 0
  && hanziOf(word).length === [...word.text.replace(/\s/g, "")].length;

export const shortGloss = (word: StudyWord) => word.gloss?.split(";")[0].trim() ?? "";

export function shuffled<Item>(items: readonly Item[], random: () => number = Math.random): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

export const joinParts = (parts: string[], languageCode: string) => parts.join(/^(zh|ja)\b/.test(languageCode) ? "" : " ");

/** One step of a review: a card's own question, or a board of match-the-meaning pairs. */
export type ReviewItem =
  | { id: string; kind: "card"; card: ReviewCard }
  | { id: string; kind: "match"; cards: ReviewCard[]; meanings: string[] };

/** The server's cards in order; the match cards are gathered into boards of up to four pairs, each where its first
 * card was. A last single pair joins the board before it. */
export function reviewItems(cards: ReviewCard[], random: () => number = Math.random): ReviewItem[] {
  const matches = cards.filter((card) => card.exercise.type === "match");
  const boards: ReviewCard[][] = [];
  for (let start = 0; start < matches.length; start += MAX_MATCH_PAIRS) boards.push(matches.slice(start, start + MAX_MATCH_PAIRS));
  if (boards.length > 1 && boards[boards.length - 1].length === 1) boards[boards.length - 2].push(...boards.pop()!);
  const firstOfBoard = new Map(boards.map((board) => [board[0].conceptId, board]));
  const items: ReviewItem[] = [];
  for (const card of cards) {
    if (card.exercise.type !== "match") { items.push({ id: card.conceptId, kind: "card", card }); continue; }
    const board = firstOfBoard.get(card.conceptId);
    if (!board) continue;
    const meanings = board.map((item) => (item.exercise.type === "match" ? item.exercise.meaning : ""));
    items.push({ id: `match:${card.conceptId}`, kind: "match", cards: board, meanings: shuffled(meanings, random) });
  }
  return items;
}
