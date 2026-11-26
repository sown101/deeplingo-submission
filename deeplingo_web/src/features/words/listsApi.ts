import type { ApiClient } from "../../lib/api/apiClient";
import {
  parseImportReport,
  parseListDetail,
  parseListSummaries,
  parseListSummary,
  parseListWordResult,
  type ImportReport,
  type ListDetail,
  type ListSummary,
  type ListWord,
} from "./listsModels";

// L1b: private named lists. Learners send names, pasted text and a choice among the meanings the
// server stored for a waiting line; they never send a concept, a user or a meaning text.
export class WordListsApi {
  constructor(private readonly client: ApiClient) {}

  async list(languageCode?: string): Promise<ListSummary[]> {
    const query = languageCode ? `?language_code=${encodeURIComponent(languageCode)}` : "";
    return parseListSummaries(await this.client.get<unknown>(`/learner/me/lists${query}`));
  }

  async create(languageCode: string, name: string): Promise<ListSummary> {
    return parseListSummary(await this.client.post<unknown>("/learner/me/lists", { language_code: languageCode, name }));
  }

  async detail(listId: string): Promise<ListDetail> {
    return parseListDetail(await this.client.get<unknown>(`/learner/me/lists/${encodeURIComponent(listId)}`));
  }

  // Deletes the list only; its words stay in My words.
  async remove(listId: string): Promise<void> {
    await this.client.request<unknown>("DELETE", `/learner/me/lists/${encodeURIComponent(listId)}`);
  }

  // At most 50 lines are read per request; the screen sends longer pastes in batches.
  async importBatch(listId: string, text: string): Promise<ImportReport> {
    return parseImportReport(await this.client.post<unknown>(`/learner/me/lists/${encodeURIComponent(listId)}/import`, { text }));
  }

  async chooseMeaning(listId: string, lineId: string, entryId: string, senseId: string): Promise<ListWord> {
    const path = `/learner/me/lists/${encodeURIComponent(listId)}/lines/${encodeURIComponent(lineId)}`;
    return parseListWordResult(await this.client.put<unknown>(path, { entry_id: entryId, sense_id: senseId }));
  }

  async dismissLine(listId: string, lineId: string): Promise<void> {
    await this.client.request<unknown>(
      "DELETE", `/learner/me/lists/${encodeURIComponent(listId)}/lines/${encodeURIComponent(lineId)}`);
  }

  // Adds a word the learner already saved; adding it twice changes nothing.
  async addWord(listId: string, conceptId: string): Promise<void> {
    await this.client.request<unknown>(
      "PUT", `/learner/me/lists/${encodeURIComponent(listId)}/words/${encodeURIComponent(conceptId)}`);
  }

  async removeWord(listId: string, conceptId: string): Promise<void> {
    await this.client.request<unknown>(
      "DELETE", `/learner/me/lists/${encodeURIComponent(listId)}/words/${encodeURIComponent(conceptId)}`);
  }
}
