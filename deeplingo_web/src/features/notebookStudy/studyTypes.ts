/** What every study mode needs to know about a word. */
export interface StudyWord {
  conceptId: string;
  languageCode: string;
  text: string;
  traditional: string | null;
  reading: string | null;
  gloss: string | null;
  note: string | null;
  favorite: boolean;
}

/** A notebook id, "all" for every saved word, or "level-0" .. "level-4" for a level of the chart. */
export type NotebookScope = string;
