import type { ApiClient } from "../../lib/api/apiClient";
import {
  parseDictionarySearch,
  parseExamples,
  parseMyWord,
  parseMyWordsView,
  type DictionaryEntryResult,
  type ExampleSentence,
  type MyWord,
  type MyWordsView,
  type WordStatus,
} from "./wordsModels";

// `acknowledge_above_level` answers the one confirmation the server asks for a word above the
// learner's declared level; it never changes anything else.
export type SaveWordRequest =
  | { source: "lookup"; library_item_id: string; segment_id: string; start_codepoint: number; end_codepoint: number; sense_id: string | null; acknowledge_above_level?: boolean; region_id?: string }
  | { source: "dictionary"; language_code: string; entry_id: string; sense_id: string; acknowledge_above_level?: boolean }
  | { source: "occurrence"; library_item_id: string; learning_object_id: string; acknowledge_above_level?: boolean; region_id?: string };

// Learners send selectors only (a lookup span, a dictionary sense or an occurrence);
// the server resolves the Concept.
export class WordsApi {
  constructor(private readonly client: ApiClient) {}

  async list(languageCode?: string, libraryItemId?: string, recognitionOnly = false): Promise<MyWordsView> {
    const params = new URLSearchParams();
    if (languageCode) params.set("language_code", languageCode);
    if (libraryItemId) params.set("library_item_id", libraryItemId);
    if (recognitionOnly) params.set("recognition_only", "true");
    const query = params.size ? `?${params.toString()}` : "";
    return parseMyWordsView(await this.client.get<unknown>(`/learner/me/words${query}`));
  }

  // Pause or resume a saved word; status remains server-owned.
  async setStatus(conceptId: string, status: WordStatus): Promise<MyWord> {
    return parseMyWord(await this.client.put<unknown>(`/learner/me/words/${encodeURIComponent(conceptId)}/status`, { status }));
  }

  async save(request: SaveWordRequest): Promise<MyWord> {
    const saved = parseMyWord(await this.client.post<unknown>("/learner/me/words", request));
    // 2026-11-05: a saved word gets its examples written in the background right away, so cards and
    // questions have context without the learner asking. Best effort: the server writes only when the word
    // has none, shares the examples rate limit, and a failure leaves "Find an example" available.
    if (saved.saved) void this.client.post<unknown>(`/learner/me/words/${encodeURIComponent(saved.conceptId)}/examples`, {}).catch(() => undefined);
    return saved;
  }

  async remove(conceptId: string): Promise<void> {
    await this.client.request<unknown>("DELETE", `/learner/me/words/${encodeURIComponent(conceptId)}`);
  }

  async search(languageCode: string, query: string): Promise<DictionaryEntryResult[]> {
    const params = `language_code=${encodeURIComponent(languageCode)}&q=${encodeURIComponent(query)}`;
    return parseDictionarySearch(await this.client.get<unknown>(`/learner/me/dictionary/search?${params}`));
  }

  // Normal reads seed a dictionary example; readOnly also prevents that shared-content write.
  async examples(conceptId: string, readOnly = false): Promise<ExampleSentence[]> {
    const query = readOnly ? "?read_only=true" : "";
    return parseExamples(await this.client.get<unknown>(`/learner/me/words/${encodeURIComponent(conceptId)}/examples${query}`));
  }

  // Asks the server to write an example for a word that has none. No content is sent.
  async writeExample(conceptId: string): Promise<ExampleSentence[]> {
    return parseExamples(await this.client.post<unknown>(`/learner/me/words/${encodeURIComponent(conceptId)}/examples`, {}));
  }
}
