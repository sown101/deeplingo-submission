// The review engine's wire format (backend practice module). The client only ever sees prompts; answers are graded
// on the server, and a malformed response is rejected rather than shown.

/** What the notebook's Review asks the server for. Pronunciation and writing are practice: graded and
 * logged, never moving the review schedule (owner decision 2026-11-14). */
export type ServerType = "choice" | "listening" | "match" | "order" | "pronunciation" | "writing";

export interface Deck { languageCode: string; dueCount: number; newCount: number; totalCount: number }

export type Exercise =
  | { type: "choice"; text: string; reading: string | null; sentence: string | null; options: string[] }
  | { type: "listening"; options: string[] }
  | { type: "match"; text: string; reading: string | null; meaning: string }
  | { type: "order"; kind: "sentence" | "characters"; parts: string[]; meaning: string | null }
  | { type: "pronunciation"; text: string; reading: string | null; meaning: string | null }
  | { type: "writing"; script: "strokes"; characters: string; reading: string | null; meaning: string | null };

export interface ReviewCard { conceptId: string; text: string; reading: string | null; isNew: boolean; exercise: Exercise }

export interface DueCards { languageCode: string; dueCount: number; newCount: number; cards: ReviewCard[] }

export type WordErrorType = "none" | "mispronunciation" | "omission" | "insertion" | "unexpected_break" | "missing_break" | "monotone" | "other";
export type Band = "excellent" | "good" | "fair" | "retry";

/** Azure's whole result for one attempt at a word: every score, and each word (a Chinese character is one) with its
 * error type and phonemes. */
export interface PronunciationAssessment {
  band: Band;
  scores: { pronunciation: number; accuracy: number; fluency: number; completeness: number; prosody: number | null };
  words: { word: string; accuracy: number; error_type: WordErrorType; phonemes: { phoneme: string; accuracy: number }[] }[];
}

export interface LatestPronunciation { score: number; band: Band | null; at: string | null; assessment: PronunciationAssessment | null }

export interface AnswerResult {
  conceptId: string;
  correct: boolean;
  outcome: string | null;
  grade: "again" | "hard" | "good" | "easy" | null;
  scheduled: boolean;
  nextReviewAt: string | null;
  expected: string;
  duplicate: boolean;
  assessment: PronunciationAssessment | null;
}

export type Answer =
  | { option: string }
  | { dont_know: true }
  | { text: string; mistakes?: number; ignore_accents?: boolean };

const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const isScore = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;
const optionalText = (value: unknown): string | null => (typeof value === "string" && value.length > 0 ? value : null);
const fail = (what: string): never => { throw new Error(`Invalid review response: ${what}`); };

const BANDS: readonly string[] = ["excellent", "good", "fair", "retry"];
const ERROR_TYPES: readonly string[] = ["none", "mispronunciation", "omission", "insertion", "unexpected_break", "missing_break", "monotone", "other"];

export function parseDecks(raw: unknown): Deck[] {
  if (!isObject(raw) || !Array.isArray(raw.decks)) return fail("decks");
  return raw.decks.map((deck) => {
    if (!isObject(deck) || !isText(deck.language_code) || !isCount(deck.due_count) || !isCount(deck.new_count)
      || !isCount(deck.total_count)) return fail("deck");
    return { languageCode: deck.language_code, dueCount: deck.due_count, newCount: deck.new_count, totalCount: deck.total_count };
  });
}

function parseOptions(raw: unknown): string[] {
  if (!Array.isArray(raw) || raw.length < 2 || !raw.every(isText) || new Set(raw).size !== raw.length) return fail("options");
  return raw;
}

export function parseExercise(raw: unknown): Exercise {
  if (!isObject(raw) || !isObject(raw.prompt)) return fail("exercise");
  const prompt = raw.prompt;
  switch (raw.type) {
    case "choice":
      if (!isText(prompt.text)) return fail("choice");
      return { type: "choice", text: prompt.text, reading: optionalText(prompt.reading), sentence: optionalText(prompt.sentence),
        options: parseOptions(prompt.options) };
    case "listening":
      return { type: "listening", options: parseOptions(prompt.options) };
    case "match":
      if (!isText(prompt.text) || !isText(prompt.meaning)) return fail("match");
      return { type: "match", text: prompt.text, reading: optionalText(prompt.reading), meaning: prompt.meaning };
    case "order":
      if ((prompt.kind !== "sentence" && prompt.kind !== "characters") || !Array.isArray(prompt.parts) || prompt.parts.length < 2
        || !prompt.parts.every(isText)) return fail("order");
      return { type: "order", kind: prompt.kind, parts: prompt.parts, meaning: optionalText(prompt.meaning) };
    case "pronunciation":
      if (!isText(prompt.text)) return fail("pronunciation");
      return { type: "pronunciation", text: prompt.text, reading: optionalText(prompt.reading), meaning: optionalText(prompt.meaning) };
    case "writing":
      if (prompt.script === "strokes" && isText(prompt.characters)) {
        return { type: "writing", script: "strokes", characters: prompt.characters, reading: optionalText(prompt.reading),
          meaning: optionalText(prompt.meaning) };
      }
      return fail("writing");
    default:
      return fail("exercise type");
  }
}

export function parseDue(raw: unknown): DueCards {
  if (!isObject(raw) || !isText(raw.language_code) || !isCount(raw.due_count) || !isCount(raw.new_count) || !Array.isArray(raw.cards)) {
    return fail("due");
  }
  const cards = raw.cards.map((card) => {
    if (!isObject(card) || !isText(card.concept_id) || !isText(card.text) || typeof card.is_new !== "boolean") return fail("card");
    return { conceptId: card.concept_id, text: card.text, reading: optionalText(card.reading), isNew: card.is_new,
      exercise: parseExercise(card.exercise) };
  });
  return { languageCode: raw.language_code, dueCount: raw.due_count, newCount: raw.new_count, cards };
}

export function parseAssessment(raw: unknown): PronunciationAssessment {
  if (!isObject(raw) || !BANDS.includes(raw.band as string) || !isObject(raw.scores) || !Array.isArray(raw.words)) return fail("assessment");
  const scores = raw.scores;
  if (!isScore(scores.pronunciation) || !isScore(scores.accuracy) || !isScore(scores.fluency) || !isScore(scores.completeness)
    || !(scores.prosody === null || scores.prosody === undefined || isScore(scores.prosody))) return fail("scores");
  const words = raw.words.map((word) => {
    if (!isObject(word) || !isText(word.word) || !isScore(word.accuracy) || !ERROR_TYPES.includes(word.error_type as string)
      || !Array.isArray(word.phonemes)) return fail("word");
    const phonemes = word.phonemes.map((item) => {
      if (!isObject(item) || !isText(item.phoneme) || !isScore(item.accuracy)) return fail("phoneme");
      return { phoneme: item.phoneme, accuracy: item.accuracy };
    });
    return { word: word.word, accuracy: word.accuracy, error_type: word.error_type as WordErrorType, phonemes };
  });
  return {
    band: raw.band as Band,
    scores: { pronunciation: scores.pronunciation, accuracy: scores.accuracy, fluency: scores.fluency, completeness: scores.completeness,
      prosody: isScore(scores.prosody) ? scores.prosody : null },
    words,
  };
}

export function parseAnswer(raw: unknown, conceptId: string): AnswerResult {
  if (!isObject(raw) || raw.concept_id !== conceptId || typeof raw.correct !== "boolean" || typeof raw.scheduled !== "boolean"
    || typeof raw.expected !== "string" || typeof raw.duplicate !== "boolean") return fail("answer");
  const grade = raw.grade === "again" || raw.grade === "hard" || raw.grade === "good" || raw.grade === "easy" ? raw.grade : null;
  return { conceptId, correct: raw.correct, outcome: optionalText(raw.outcome), grade, scheduled: raw.scheduled,
    nextReviewAt: optionalText(raw.next_review_at), expected: raw.expected, duplicate: raw.duplicate,
    assessment: raw.assessment === null || raw.assessment === undefined ? null : parseAssessment(raw.assessment) };
}

export function parseLatestPronunciation(raw: unknown, conceptId: string): LatestPronunciation | null {
  if (!isObject(raw) || raw.concept_id !== conceptId) return fail("latest pronunciation");
  const latest = raw.latest;
  if (latest === null || latest === undefined) return null;
  if (!isObject(latest) || !isScore(latest.score)) return fail("latest pronunciation");
  const band = BANDS.includes(latest.band as string) ? latest.band as Band : null;
  return { score: latest.score, band, at: optionalText(latest.occurred_at),
    assessment: isObject(latest.assessment) ? parseAssessment({ band: band ?? "retry", ...latest.assessment }) : null };
}

/** A review run's id for "one schedule change per card per pass". */
export function newPassId(): string {
  return `pass-${crypto.randomUUID()}`;
}

export function newEventId(): string {
  return crypto.randomUUID();
}

// --- Grammar ---------------------------------------------------------------------------------------------------

export interface GrammarLesson { summary: string; rules: string[]; examples: { text: string; meaning: string }[]; mistakes?: { wrong: string; right: string; why: string }[] }
export interface GrammarPoint {
  key: string; title: string; topicKey: string; lesson: GrammarLesson | null; exerciseCount: number;
  attempts: number; correctCount: number; incorrectCount: number; lessonLearnedAt: string | null;
}
export interface GrammarRedo { requestId: string; grammarKey: string; title: string; level: string | null; reason: string | null }
export interface GrammarOverview {
  languageCode: string; levels: string[]; level: string | null; topics: { key: string; title: string }[];
  points: GrammarPoint[]; redo: GrammarRedo[];
}
export interface GrammarExercise { id: string; grammarKey: string; prompt: string; options: { id: string; text: string }[] }
export interface GrammarGrade { exerciseId: string; correct: boolean; correctOptionId: string; explanation: string; redoClosed: number }

function parseLesson(raw: unknown): GrammarLesson | null {
  if (raw === null || raw === undefined) return null;
  if (!isObject(raw) || !isText(raw.summary) || !Array.isArray(raw.rules) || !raw.rules.every(isText) || !Array.isArray(raw.examples)
    || !raw.examples.every((item) => isObject(item) && isText(item.text) && isText(item.meaning))) return fail("lesson");
  const mistakes = Array.isArray(raw.mistakes) && raw.mistakes.every((item) => isObject(item) && isText(item.wrong) && isText(item.right) && isText(item.why))
    ? raw.mistakes as GrammarLesson["mistakes"] : [];
  return { summary: raw.summary, rules: raw.rules, examples: raw.examples as GrammarLesson["examples"], mistakes };
}

export function parseGrammarOverview(raw: unknown): GrammarOverview {
  if (!isObject(raw) || !isText(raw.language_code) || !Array.isArray(raw.levels) || !raw.levels.every(isText)
    || !Array.isArray(raw.topics) || !Array.isArray(raw.points) || !Array.isArray(raw.redo)) return fail("grammar");
  const topics = raw.topics.map((topic) => {
    if (!isObject(topic) || !isText(topic.key) || !isText(topic.title)) return fail("topic");
    return { key: topic.key, title: topic.title };
  });
  const points = raw.points.map((point): GrammarPoint => {
    if (!isObject(point) || !isText(point.key) || !isText(point.title) || !isText(point.topic_key) || !isCount(point.attempts)
      || !isCount(point.correct_count) || !isCount(point.incorrect_count) || !isCount(point.exercise_count)) return fail("point");
    return { key: point.key, title: point.title, topicKey: point.topic_key, lesson: parseLesson(point.lesson), exerciseCount: point.exercise_count,
      attempts: point.attempts, correctCount: point.correct_count, incorrectCount: point.incorrect_count,
      lessonLearnedAt: optionalText(point.lesson_learned_at) };
  });
  const redo = raw.redo.map((item): GrammarRedo => {
    if (!isObject(item) || !isText(item.request_id) || !isText(item.grammar_key) || !isText(item.title)) return fail("redo");
    return { requestId: item.request_id, grammarKey: item.grammar_key, title: item.title, level: optionalText(item.level),
      reason: optionalText(item.reason) };
  });
  return { languageCode: raw.language_code, levels: raw.levels, level: optionalText(raw.level), topics, points, redo };
}

export function parseGrammarExercises(raw: unknown): GrammarExercise[] {
  if (!isObject(raw) || !Array.isArray(raw.exercises)) return fail("exercises");
  return raw.exercises.map((item) => {
    if (!isObject(item) || !isText(item.id) || !isText(item.grammar_key) || !isText(item.prompt) || !Array.isArray(item.options)
      || item.options.length < 2 || !item.options.every((option) => isObject(option) && isText(option.id) && isText(option.text))) return fail("exercise");
    return { id: item.id, grammarKey: item.grammar_key, prompt: item.prompt, options: item.options as { id: string; text: string }[] };
  });
}

export function parseGrammarGrade(raw: unknown, exercise: GrammarExercise): GrammarGrade {
  if (!isObject(raw) || raw.exercise_id !== exercise.id || typeof raw.correct !== "boolean" || !isText(raw.explanation)
    || !exercise.options.some((option) => option.id === raw.correct_option_id)) return fail("grammar grade");
  return { exerciseId: exercise.id, correct: raw.correct, correctOptionId: raw.correct_option_id as string, explanation: raw.explanation,
    redoClosed: isCount(raw.redo_closed) ? raw.redo_closed : 0 };
}
