import { ApiError } from "../../../lib/api/errors";

// M1 S6 region questions: comprehension practice about the study part. The server sends the
// questions without their answers and checks the chosen option; nothing here is a score.

// `not_prepared`: no preparation was started for this part; only `preparing` is worth reading again.
export const QUESTIONS_STATES = ["no_region", "not_prepared", "preparing", "ready", "none", "unavailable"] as const;
export type QuestionsState = (typeof QUESTIONS_STATES)[number];

export interface RegionQuestion {
  id: string;
  position: number;
  question: string;
  options: string[];
}

export interface RegionQuestionsView {
  status: QuestionsState;
  questions: RegionQuestion[];
}

export interface QuestionAnswer {
  question_id: string;
  selected_option: number;
  correct: boolean;
  correct_index: number;
  evidence_segment_id: string;
  evidence_quote: string;
  explanation: string;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function fail(): never {
  throw new ApiError("parse", null, { message: "Invalid questions response" });
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : fail();
}

function uuid(value: unknown): string {
  return typeof value === "string" && UUID_RE.test(value) ? value : fail();
}

function text(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : fail();
}

function option(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 3 ? value : fail();
}

export function parseRegionQuestions(raw: unknown): RegionQuestionsView {
  const r = record(raw);
  const status = QUESTIONS_STATES.find((state) => state === r.status) ?? fail();
  const list = Array.isArray(r.questions) ? r.questions : fail();
  const questions = list.map((item) => {
    const q = record(item);
    const options = Array.isArray(q.options) && q.options.length === 4 ? q.options.map(text) : fail();
    const position = typeof q.position === "number" && Number.isInteger(q.position) ? q.position : fail();
    return { id: uuid(q.id), position, question: text(q.question), options };
  });
  if (status !== "ready" && questions.length > 0) fail();
  return { status, questions: questions.sort((a, b) => a.position - b.position) };
}

// An answer to a different question is never applied to this one.
export function parseQuestionAnswer(raw: unknown, questionId: string): QuestionAnswer {
  const r = record(raw);
  const id = uuid(r.question_id);
  if (id.toLowerCase() !== questionId.toLowerCase() || typeof r.correct !== "boolean") fail();
  return {
    question_id: id,
    selected_option: option(r.selected_option),
    correct: r.correct,
    correct_index: option(r.correct_index),
    evidence_segment_id: uuid(r.evidence_segment_id),
    evidence_quote: text(r.evidence_quote),
    explanation: text(r.explanation),
  };
}
