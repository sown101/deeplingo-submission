import type { ApiClient } from "../../lib/api/apiClient";
import {
  parseAnswer,
  parseDecks,
  parseDue,
  parseGrammarExercises,
  parseGrammarGrade,
  parseGrammarOverview,
  parseLatestPronunciation,
  type Answer,
  type AnswerResult,
  type Deck,
  type DueCards,
  type GrammarExercise,
  type GrammarGrade,
  type GrammarOverview,
  type LatestPronunciation,
  type ServerType,
} from "./reviewModels";

export interface AnswerRequest {
  clientEventId: string;
  passId: string | null;
  conceptId: string;
  languageCode: string;
  exerciseType: Exclude<ServerType, "pronunciation">;
  answer: Answer;
  hintUsed: boolean;
  responseMs: number | null;
}

/** The notebook's review decks and grammar. The client sends selectors and the learner's own input only. */
export class ReviewApi {
  constructor(private readonly client: ApiClient) {}

  async decks(): Promise<Deck[]> {
    return parseDecks(await this.client.get<unknown>("/learner/me/review/decks"));
  }

  /** One review run: the deck's due cards, or exactly the chosen words, each with one of the chosen types. */
  async due(language: string, types: ServerType[], conceptIds: string[] = []): Promise<DueCards> {
    const params = new URLSearchParams({ types: types.join(","), limit: String(conceptIds.length ? Math.min(conceptIds.length, 50) : 20) });
    conceptIds.slice(0, 50).forEach((id) => params.append("concept_ids", id));
    return parseDue(await this.client.get<unknown>(`/learner/me/review/${encodeURIComponent(language)}/due?${params}`));
  }

  async answer(request: AnswerRequest): Promise<AnswerResult> {
    const raw = await this.client.post<unknown>("/learner/me/review/answers", {
      client_event_id: request.clientEventId, pass_id: request.passId, concept_id: request.conceptId,
      language_code: request.languageCode, exercise_type: request.exerciseType, answer: request.answer,
      hint_used: request.hintUsed, response_ms: request.responseMs,
    });
    return parseAnswer(raw, request.conceptId);
  }

  /** The word said aloud, assessed by Azure on the server; practice only, so the schedule never moves. */
  async answerPronunciation(request: { clientEventId: string; passId: string | null; conceptId: string; languageCode: string }, wav: Blob): Promise<AnswerResult> {
    const form = new FormData();
    form.set("client_event_id", request.clientEventId);
    if (request.passId) form.set("pass_id", request.passId);
    form.set("concept_id", request.conceptId);
    form.set("language_code", request.languageCode);
    form.set("audio", wav, "word.wav");
    return parseAnswer(await this.client.postForm<unknown>("/learner/me/review/answers/pronunciation", form), request.conceptId);
  }

  /** The card's word read aloud, chosen by id so the listening question does not show its answer. */
  async audioUrl(conceptId: string): Promise<string> {
    const blob = await this.client.get<Blob>(`/learner/me/review/cards/${encodeURIComponent(conceptId)}/audio`, { blob: true });
    return URL.createObjectURL(blob);
  }

  async latestPronunciation(conceptId: string): Promise<LatestPronunciation | null> {
    return parseLatestPronunciation(await this.client.get<unknown>(`/learner/me/words/${encodeURIComponent(conceptId)}/pronunciation`), conceptId);
  }

  async grammar(language: string, level?: string): Promise<GrammarOverview> {
    return parseGrammarOverview(await this.client.get<unknown>(`/learner/me/grammar/${encodeURIComponent(language)}`,
      level ? { query: { level } } : undefined));
  }

  async grammarExercises(language: string, scope: { level?: string; grammarKey?: string }): Promise<GrammarExercise[]> {
    const query: Record<string, string> = {};
    if (scope.level) query.level = scope.level;
    if (scope.grammarKey) query.grammar_key = scope.grammarKey;
    return parseGrammarExercises(await this.client.get<unknown>(`/learner/me/grammar/${encodeURIComponent(language)}/exercises`, { query }));
  }

  async grammarAnswer(language: string, exercise: GrammarExercise, optionId: string, clientEventId: string): Promise<GrammarGrade> {
    const raw = await this.client.post<unknown>("/learner/me/grammar/answers", {
      language_code: language, exercise_id: exercise.id, option_id: optionId, client_event_id: clientEventId,
    });
    return parseGrammarGrade(raw, exercise);
  }

  async grammarLessonLearned(language: string, grammarKey: string, clientEventId: string): Promise<void> {
    await this.client.post<unknown>("/learner/me/grammar/lessons", { language_code: language, grammar_key: grammarKey, client_event_id: clientEventId });
  }
}
