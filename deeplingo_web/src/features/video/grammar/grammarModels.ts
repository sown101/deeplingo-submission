import { ApiError } from "../../../lib/api/errors";

export type GrammarScope = "selection" | "sentence";
export interface GrammarSection { title: string; text: string }
export interface GrammarView {
  segment_id: string;
  scope: GrammarScope;
  source_text: string;
  support_language_code: string;
  source: "curriculum_draft" | "ai_unverified";
  explanation: { sentence_structure: GrammarSection; grammar: GrammarSection; important_words: GrammarSection };
}

export function parseGrammarView(raw: unknown, segmentId: string, scope: GrammarScope): GrammarView {
  const fail = () => { throw new ApiError("parse", null, { message: "Invalid grammar explanation" }); };
  const object = (value: unknown): Record<string, unknown> =>
    value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : fail();
  const text = (value: unknown, max: number): string =>
    typeof value === "string" && value.trim() && [...value].length <= max ? value : fail();
  const r = object(raw), content = object(r.explanation);
  if (r.segment_id !== segmentId || r.scope !== scope || !["curriculum_draft", "ai_unverified"].includes(String(r.source))) fail();
  const section = (value: unknown): GrammarSection => {
    const item = object(value);
    return { title: text(item.title, 80), text: text(item.text, 1200) };
  };
  return { segment_id: segmentId, scope, source_text: text(r.source_text, 1800),
    support_language_code: text(r.support_language_code, 16), source: r.source as GrammarView["source"],
    explanation: { sentence_structure: section(content.sentence_structure), grammar: section(content.grammar),
      important_words: section(content.important_words) } };
}
