import type { StudyWord } from "../../notebookStudy/studyTypes";
import type { WordStatus } from "../wordsModels";

// What the shared Notebook page shows about a word, whether it comes from one notebook or from All words.
export interface NotebookWord extends StudyWord {
  status: WordStatus;
  rung: number;
  levelLabel: string | null;
  aboveLevel: boolean;
  saved: boolean;
  nextReviewAt: string | null;
}

export type WordOrder = "newest" | "oldest" | "az" | "za";
export interface ShowOptions { word: boolean; reading: boolean; meaning: boolean; notes: boolean }
export const DEFAULT_SHOW: ShowOptions = { word: true, reading: true, meaning: true, notes: false };

// Vietnamese meanings can be searched without typing their tone marks.
export function plain(text: string): string {
  return text.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").split(String.fromCodePoint(0x111)).join("d");
}

export function filterWords<Word extends NotebookWord>(words: readonly Word[], query: string): Word[] {
  const wanted = plain(query.trim());
  if (!wanted) return [...words];
  return words.filter(word => [word.text, word.traditional, word.reading, word.gloss].some(value => value && plain(value).includes(wanted)));
}

// The server lists the most recently saved word first, so that order is "newest".
export function orderWords<Word extends NotebookWord>(words: readonly Word[], order: WordOrder, locale?: string): Word[] {
  const sorted = [...words];
  if (order === "oldest") sorted.reverse();
  if (order === "az") sorted.sort((a, b) => a.text.localeCompare(b.text, locale));
  if (order === "za") sorted.sort((a, b) => b.text.localeCompare(a.text, locale));
  return sorted;
}

// The shelf chart has five levels; the two highest rungs share the last one.
export function levelOfRung(rung: number): number {
  return Math.min(rung, 4);
}

export function chunks<Item>(items: readonly Item[], size: number): Item[][] {
  const out: Item[][] = [];
  for (let start = 0; start < items.length; start += size) out.push(items.slice(start, start + size));
  return out;
}

export function toStudyWord(word: NotebookWord): StudyWord {
  return {
    conceptId: word.conceptId, languageCode: word.languageCode, text: word.text, traditional: word.traditional,
    reading: word.reading, gloss: word.gloss, note: word.note, favorite: word.favorite,
  };
}

// Picture and source links come from outside services; only web links are made clickable.
export function webUrl(url: string | null): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}
