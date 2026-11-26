import type { ApiClient } from "../../lib/api/apiClient";
import { parseMyWord, type MyWord } from "./wordsModels";
import { parseImportReport, type ImportReport } from "./listsModels";

export type MemoryRating = "not_yet" | "unsure" | "remembered";

export interface WordSet { key: string; languageCode: string; name: string; wordCount: number }
export interface WordSetWord { entryId: string; senseId: string; text: string; traditional: string | null; reading: string | null; meaning: string }
export interface WordSetDetail extends WordSet { offset: number; words: WordSetWord[] }
export interface WordSense { text: string; reading: string | null; partOfSpeech: string | null }
export interface WordCharacter { character: string; reading: string | null; meaning: string | null }
export interface WordCompound { text: string; reading: string | null; meaning: string | null }
export interface WordDetails {
  conceptId: string; text: string; traditional: string | null; reading: string | null; level: string | null;
  senses: WordSense[]; characters: WordCharacter[]; compounds: WordCompound[];
}
export interface WordImage {
  conceptId: string; imageUrl: string; thumbnailUrl: string | null; title: string | null;
  creator: string | null; license: string | null; sourceUrl: string | null;
}
export interface WordPronunciation { text: string; band: string; pronunciation: number; accuracy: number; fluency: number }
export interface PersonalChange { note?: string | null; favorite?: boolean }

type Raw = Record<string, any>;

const parseSet = (r: Raw): WordSet => ({ key: r.key, languageCode: r.language_code, name: r.name, wordCount: r.word_count });

// The notebook's extras: the learner's own marks, a memory rating that moves the review date only,
// read-only reference data, and words read aloud or assessed.
export class NotebookApi {
  constructor(private readonly client: ApiClient) {}

  async setPersonal(conceptId: string, change: PersonalChange): Promise<MyWord> {
    return parseMyWord(await this.client.put<unknown>(`/learner/me/words/${encodeURIComponent(conceptId)}/personal`, change));
  }

  // `keepalive` lets the last rating reach the server while the page closes.
  async rateMemory(conceptId: string, rating: MemoryRating, keepalive = false): Promise<string> {
    const raw = await this.client.post<Raw>(`/learner/me/words/${encodeURIComponent(conceptId)}/memory-rating`, { rating }, keepalive ? { keepalive } : {});
    return raw.next_review_at;
  }

  async sets(): Promise<WordSet[]> {
    return (await this.client.get<Raw[]>("/learner/me/word-sets")).map(parseSet);
  }

  async set(key: string, offset = 0): Promise<WordSetDetail> {
    const r = await this.client.get<Raw>(`/learner/me/word-sets/${encodeURIComponent(key)}?offset=${offset}`);
    return {
      ...parseSet(r), offset: r.offset,
      words: r.words.map((w: Raw) => ({ entryId: w.entry_id, senseId: w.sense_id, text: w.text, traditional: w.traditional, reading: w.reading, meaning: w.meaning })),
    };
  }

  // At most 50 entries a request; the server uses each entry's first meaning.
  async addFromSet(listId: string, entryIds: string[]): Promise<ImportReport> {
    return parseImportReport(await this.client.post<unknown>(`/learner/me/lists/${encodeURIComponent(listId)}/from-set`, { entry_ids: entryIds }));
  }

  async details(conceptId: string): Promise<WordDetails> {
    const r = await this.client.get<Raw>(`/learner/me/words/${encodeURIComponent(conceptId)}/details`);
    return {
      conceptId: r.concept_id, text: r.text, traditional: r.traditional, reading: r.reading, level: r.level,
      senses: r.senses.map((s: Raw) => ({ text: s.text, reading: s.reading, partOfSpeech: s.part_of_speech })),
      characters: r.characters, compounds: r.compounds,
    };
  }

  // At most 24 words a request; `refresh` asks for a different picture for that word.
  async images(conceptIds: string[], refresh?: string): Promise<WordImage[]> {
    const raw = await this.client.post<Raw[]>("/learner/me/words/images", { concept_ids: conceptIds, ...(refresh ? { refresh } : {}) });
    return raw.map(r => ({ conceptId: r.concept_id, imageUrl: r.image_url, thumbnailUrl: r.thumbnail_url, title: r.title, creator: r.creator, license: r.license, sourceUrl: r.source_url }));
  }

  // The word must be in the dictionary. Returns an object URL the caller plays and revokes.
  async audioUrl(languageCode: string, text: string): Promise<string> {
    const params = new URLSearchParams({ language_code: languageCode, text });
    const blob = await this.client.get<Blob>(`/learner/me/dictionary/audio?${params}`, { blob: true });
    return URL.createObjectURL(blob);
  }

  async assessPronunciation(languageCode: string, text: string, wav: Blob): Promise<WordPronunciation> {
    const form = new FormData();
    form.set("language_code", languageCode);
    form.set("text", text);
    form.set("audio", wav, "word.wav");
    return this.client.postForm<WordPronunciation>("/learner/me/dictionary/pronunciation", form);
  }
}
