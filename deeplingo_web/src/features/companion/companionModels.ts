import { ApiError } from "../../lib/api/errors";
import { parsePlanItem, type PlanItem, type PlanItemKind } from "../plan/planModels";
import { parseAnalysisReference, type AnalysisReference } from "./sessionAnalysisModels";
import type { OpeningChoice } from "./realtimeClient";

export interface CompanionFeedback { analysis?: AnalysisReference; weak_words: string[] }

export function parseCompanionFeedback(value: unknown): CompanionFeedback {
  const r = obj(value, "conversation feedback");
  const weak = r.weak_words ?? [];
  if (!Array.isArray(weak) || weak.length > 6 || weak.some(word => typeof word !== "string" || !word.trim() || word.length > 200)) fail("Invalid pronunciation feedback");
  const analysis = parseAnalysisReference(r.analysis);
  if (r.analysis != null && !analysis) fail("Invalid speaking analysis");
  return { analysis, weak_words: weak as string[] };
}

// Voice companion turn. Practice only: the backend builds the context,
// validates the model turn and returns text, hints and reply audio. Nothing here
// is learner state, and the client never decides correctness.

export type CompanionEntry = "video" | "review" | "home";
/** A help button in the text conversation; sent as `request`, like the voice screen's buttons. */
export type CompanionRequest = "hint" | "explain" | "natural" | "suggest";

/** A card the agent put on screen that does something for the learner (voice event and text turn share this shape).
 * Opening ones only prepare a screen: the learner taps one button; nothing navigates on its own. */
export type AgentAction =
  | { action: "open_review"; language_code: string; concept_ids: string[] }
  | { action: "open_video_region"; library_item_id: string; region_id: string; title: string | null; start_ms: number }
  | { action: "today_edited"; change: "added" | "removed"; item_id: string; kind: PlanItemKind; minutes: number; title: string | null };

const LANGUAGE_RE = /^[a-z]{2,8}$/;
const REGION_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const PLAN_KINDS = ["review", "conversation", "video_practice", "my_words", "add_video"] as const;
const MAX_ACTION_WORDS = 20;

/** Strict: anything malformed or unknown is null, so it is dropped and never rendered. */
export function parseAgentAction(raw: unknown): AgentAction | null {
  try {
    const r = obj(raw, "action");
    if (r.action === "open_review") {
      const language = text(r.language_code, "language");
      const ids = r.concept_ids;
      if (!LANGUAGE_RE.test(language) || !Array.isArray(ids) || ids.length === 0 || ids.length > MAX_ACTION_WORDS
        || ids.some((id) => typeof id !== "string" || !UUID_RE.test(id))) return null;
      return { action: "open_review", language_code: language, concept_ids: ids as string[] };
    }
    if (r.action === "open_video_region") {
      const item = text(r.library_item_id, "library item");
      const region = text(r.region_id, "region");
      if (!UUID_RE.test(item) || !REGION_RE.test(region)) return null;
      return { action: "open_video_region", library_item_id: item, region_id: region,
               title: nullableText(r.title, "title"), start_ms: int(r.start_ms, "start") };
    }
    if (r.action === "today_edited") {
      const item = text(r.item_id, "plan item");
      const minutes = int(r.minutes, "minutes");
      if (!UUID_RE.test(item) || minutes < 1) return null;
      return { action: "today_edited", change: oneOf(r.change, ["added", "removed"] as const, "change"), item_id: item,
               kind: oneOf(r.kind, PLAN_KINDS, "task kind"), minutes, title: nullableText(r.title, "title") };
    }
  } catch {
    // Malformed: dropped.
  }
  return null;
}
export type CompanionNext = "continue" | "retry" | "close";

export interface RoleplayScenario { id: string; title: string; context: string; roles: [string, string]; goals: [string, string] }
export function parseRoleplayScenarios(raw: unknown): RoleplayScenario[] {
  if (!Array.isArray(raw) || raw.length > 30) fail("Invalid situations");
  const ids = new Set<string>();
  return raw.map(value => {
    const r = obj(value, "situation"), id = text(r.id, "situation id");
    if (!/^[a-z][a-z0-9-]{0,39}$/.test(id) || ids.has(id)) fail("Invalid situation id");
    ids.add(id);
    function pair(value: unknown): [string, string] {
      if (!Array.isArray(value) || value.length !== 2) fail("Invalid situation roles");
      return [text(value[0], "role"), text(value[1], "role")];
    }
    return { id, title: text(r.title, "title"), context: text(r.context, "context"), roles: pair(r.roles), goals: pair(r.goals) };
  });
}

export interface CompanionItem {
  id: string;
  text: string;
  meaning: string | null;
}

export interface CompanionHints {
  question: string | null;
  items: CompanionItem[];
  frame: { frame: string; reason: string } | null;
  model_sentence: string | null;
}

export interface CompanionCorrection {
  quote: string;
  suggestion: string;
  note: string;
}

/** A grammar explanation the agent chose to show: an approved lesson, or AI-written text marked unverified. */
export interface CompanionGrammar {
  title: string | null;
  explanation: string;
  example: string | null;
  rules: string[];
  unverified: boolean;
}

/** One sayable sentence with a short explanation (a more natural way, or an idea for the next answer). */
export interface CompanionOption { sentence: string; explanation: string }

/** A word the companion looked up: dictionary text with its source, not model text. */
export interface LookedUpWord {
  word: string;
  headword: string;
  senses: { text: string; part_of_speech: string | null }[];
  source_name: string | null;
  source_license: string | null;
  source_url: string | null;
}

// M1 S3: the companion suggests one practice tool on one line of the study region. It is only
// a suggestion: the client opens the tool when the learner asks for it.
export interface PracticeSuggestion {
  tool: "dictation" | "shadowing";
  segment_id: string;
  start_ms: number;
  end_ms: number;
  reason: string;
}

export interface CompanionTurn extends CompanionFeedback {
  session_ticket: string | null;
  turn: number;
  max_turns: number;
  finished: boolean;
  language_code: string;
  support_language_code: string;
  entry: CompanionEntry;
  library_item_id: string | null;
  topic: string;
  learner_transcript: string | null;
  reply: string;
  reply_support: string;
  hints: CompanionHints;
  correction: CompanionCorrection | null;
  used_items: CompanionItem[];
  next: CompanionNext;
  audio: { mime_type: string; base64: string } | null;
  looked_up: LookedUpWord[];
  /** Next steps added to today's plan when the conversation ended. */
  follow_ups: PlanItem[];
  practice_suggestion: PracticeSuggestion | null;
  /** The learner hesitated: the server opens its hint ladder at this step (1-3) without a tap. */
  auto_hint_level: 1 | 2 | 3 | null;
  /** Practice this turn added to the learner's notebook (a corrected grammar point). */
  study_request: { kind: "grammar_redo" | "word_review"; item: string; title: string | null } | null;
  /** Help the agent chose to show without a tap. Optional: a malformed value is dropped, never breaks the turn. */
  grammar: CompanionGrammar | null;
  natural: CompanionOption[];
  suggestions: CompanionOption[];
  /** What the agent offers when no topic was chosen: it greets, asks what the learner wants and picks nothing. */
  choices: OpeningChoice[];
  /** Action cards of this turn (a review or a video part ready to open, a change to today's tasks); malformed ones are dropped. */
  actions: AgentAction[];
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const AUDIO_TYPES = ["audio/mpeg", "audio/wav", "audio/ogg"] as const;
const BASE64_RE = /^[A-Za-z0-9+/]+={0,2}$/;

function fail(message: string): never {
  throw new ApiError("parse", null, { message });
}

function obj(value: unknown, what: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(`Invalid ${what}`);
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string" || value.trim().length === 0) fail(`Invalid ${what}`);
  return value;
}

function nullableText(value: unknown, what: string): string | null {
  return value == null ? null : text(value, what);
}

function int(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) fail(`Invalid ${what}`);
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) fail(`Invalid ${what}`);
  return value as T;
}

function items(value: unknown, what: string): CompanionItem[] {
  if (!Array.isArray(value)) fail(`Invalid ${what}`);
  return value.map((raw) => {
    const r = obj(raw, what);
    return { id: text(r.id, "item id"), text: text(r.text, "item text"), meaning: nullableText(r.meaning, "item meaning") };
  });
}

function hintLevel(value: unknown): 1 | 2 | 3 {
  if (value !== 1 && value !== 2 && value !== 3) fail("Invalid hint level");
  return value;
}

function openingChoices(raw: unknown): OpeningChoice[] {
  if (!Array.isArray(raw)) fail("Invalid choices");
  return raw.slice(0, 4).map((value) => {
    const c = obj(value, "choice");
    return { id: oneOf(c.id, ["video", "words", "roleplay", "free"] as const, "choice"),
             count: c.count == null ? null : int(c.count, "choice count") };
  });
}

function studyRequest(raw: unknown): CompanionTurn["study_request"] {
  const r = obj(raw, "study request");
  return { kind: oneOf(r.kind, ["grammar_redo", "word_review"] as const, "study request kind"),
           item: text(r.item, "study request item"), title: nullableText(r.title, "study request title") };
}

/** One part of a reply's speech, as streamed; null for anything malformed. */
export function parseCompanionAudio(raw: unknown): { mime_type: string; base64: string } | null {
  try {
    const a = obj(raw, "audio");
    const audio = { mime_type: oneOf(a.mime_type, AUDIO_TYPES, "audio type"), base64: text(a.base64, "audio") };
    return BASE64_RE.test(audio.base64) ? audio : null;
  } catch {
    return null;
  }
}

export function parseCompanionTurn(raw: unknown): CompanionTurn {
  const r = obj(raw, "companion turn");
  const finished = r.finished;
  if (typeof finished !== "boolean") fail("Invalid finished");
  const ticket = nullableText(r.session_ticket, "session ticket");
  // A running session must carry a ticket; a finished one must not.
  if (finished === (ticket !== null)) fail("Invalid session state");
  const turn = int(r.turn, "turn");
  const maxTurns = int(r.max_turns, "max turns");
  if (maxTurns === 0 || turn > maxTurns) fail("Invalid turn");
  const libraryItem = nullableText(r.library_item_id, "library item");
  if (libraryItem !== null && !UUID_RE.test(libraryItem)) fail("Invalid library item");

  const h = obj(r.hints, "hints");
  const frame = h.frame == null ? null : obj(h.frame, "frame");
  const c = r.correction == null ? null : obj(r.correction, "correction");
  const a = r.audio == null ? null : obj(r.audio, "audio");
  // "streaming": the speech follows sentence by sentence on /turns/stream (parseCompanionAudio).
  const audioStatus = oneOf(r.audio_status, ["ready", "unavailable", "streaming"] as const, "audio status");
  if ((audioStatus === "ready") !== (a !== null)) fail("Invalid audio");
  const audio = a
    ? { mime_type: oneOf(a.mime_type, AUDIO_TYPES, "audio type"), base64: text(a.base64, "audio") }
    : null;
  if (audio && !BASE64_RE.test(audio.base64)) fail("Invalid audio");

  return {
    ...parseCompanionFeedback(r),
    session_ticket: ticket,
    turn,
    max_turns: maxTurns,
    finished,
    language_code: text(r.language_code, "language"),
    support_language_code: text(r.support_language_code, "support language"),
    entry: oneOf(r.entry, ["video", "review", "home"] as const, "entry"),
    library_item_id: libraryItem,
    topic: text(r.topic, "topic"),
    learner_transcript: nullableText(r.learner_transcript, "transcript"),
    reply: text(r.reply, "reply"),
    reply_support: text(r.reply_support, "reply support"),
    hints: {
      question: nullableText(h.question, "hint question"),
      items: items(h.items, "hint items"),
      frame: frame ? { frame: text(frame.frame, "frame"), reason: text(frame.reason, "frame reason") } : null,
      model_sentence: nullableText(h.model_sentence, "model sentence"),
    },
    correction: c
      ? { quote: text(c.quote, "quote"), suggestion: text(c.suggestion, "suggestion"), note: text(c.note, "note") }
      : null,
    used_items: items(r.used_items, "used items"),
    next: oneOf(r.next, ["continue", "retry", "close"] as const, "next"),
    audio,
    // Older backends omit looked_up (before the dictionary lookup tool): no lookups.
    looked_up: r.looked_up == null ? [] : lookedUp(r.looked_up),
    follow_ups: r.follow_ups == null ? [] : followUps(r.follow_ups),
    // Older backends omit it (before M1 S3): no suggestion.
    practice_suggestion: r.practice_suggestion == null ? null : practiceSuggestion(r.practice_suggestion),
    auto_hint_level: r.auto_hint_level == null ? null : hintLevel(r.auto_hint_level),
    study_request: r.study_request == null ? null : studyRequest(r.study_request),
    choices: r.choices == null ? [] : openingChoices(r.choices),
    grammar: optionalHelp(() => grammar(r.grammar), null),
    natural: optionalHelp(() => options(r.natural), []),
    suggestions: optionalHelp(() => options(r.suggestions), []),
    actions: Array.isArray(r.actions) ? r.actions.flatMap((value) => { const card = parseAgentAction(value); return card ? [card] : []; }).slice(0, 3) : [],
  };
}

// Optional help is an extra: an unknown or malformed value is left out and the turn still works.
function optionalHelp<T>(read: () => T, none: T): T {
  try { return read(); } catch { return none; }
}

function grammar(value: unknown): CompanionGrammar | null {
  if (value == null) return null;
  const g = obj(value, "grammar");
  if (g.unverified != null && typeof g.unverified !== "boolean") fail("Invalid grammar flag");
  return {
    title: nullableText(g.title, "grammar title"),
    explanation: text(g.explanation, "grammar explanation"),
    example: nullableText(g.example, "grammar example"),
    rules: Array.isArray(g.rules) ? g.rules.filter((rule): rule is string => typeof rule === "string" && rule.trim().length > 0).slice(0, 6) : [],
    unverified: g.unverified === true,
  };
}

function options(value: unknown): CompanionOption[] {
  if (value == null) return [];
  if (!Array.isArray(value)) fail("Invalid options");
  return value.slice(0, 5).map((raw) => {
    const o = obj(raw, "option");
    return { sentence: text(o.sentence, "option sentence"), explanation: text(o.explanation, "option explanation") };
  });
}

function practiceSuggestion(value: unknown): PracticeSuggestion {
  const s = obj(value, "practice suggestion");
  const segment = text(s.segment_id, "suggested segment");
  if (!UUID_RE.test(segment)) fail("Invalid suggested segment");
  const start = int(s.start_ms, "suggested start");
  const end = int(s.end_ms, "suggested end");
  if (end <= start) fail("Invalid suggested time");
  return {
    tool: oneOf(s.tool, ["dictation", "shadowing"] as const, "suggested tool"),
    segment_id: segment,
    start_ms: start,
    end_ms: end,
    reason: text(s.reason, "suggestion reason"),
  };
}

function followUps(value: unknown): PlanItem[] {
  if (!Array.isArray(value)) fail("Invalid follow-ups");
  return value.map(parsePlanItem);
}

function lookedUp(value: unknown): LookedUpWord[] {
  if (!Array.isArray(value)) fail("Invalid looked up words");
  return value.map((raw) => {
    const w = obj(raw, "looked up word");
    if (!Array.isArray(w.senses) || w.senses.length === 0) fail("Invalid looked up senses");
    const url = nullableText(w.source_url, "source url");
    // Only a plain https link is rendered as a link.
    if (url !== null && !/^https:\/\/[^\s"'<>]+$/.test(url)) fail("Invalid source url");
    return {
      word: text(w.word, "looked up word"),
      headword: text(w.headword, "headword"),
      senses: w.senses.map((s) => {
        const sense = obj(s, "sense");
        return { text: text(sense.text, "sense"), part_of_speech: nullableText(sense.part_of_speech, "part of speech") };
      }),
      source_name: nullableText(w.source_name, "source name"),
      source_license: nullableText(w.source_license, "source license"),
      source_url: url,
    };
  });
}


export type AgentConsent = { status: "ask" | "granted" | "revoked"; decided_at: string | null };
export type AgentSignalKind = "topic" | "goal" | "error_type" | "pace" | "turn_length";
export type AgentSignal = { id: string; language_code: string; kind: AgentSignalKind; code: string; usage_count: number };

export function parseAgentConsent(raw: unknown): AgentConsent {
  const r = obj(raw, "agent consent");
  return {
    status: oneOf(r.status, ["ask", "granted", "revoked"] as const, "consent status"),
    decided_at: nullableText(r.decided_at, "consent time"),
  };
}

export function parseAgentSignals(raw: unknown): AgentSignal[] {
  const r = obj(raw, "agent signals");
  if (!Array.isArray(r.signals)) fail("Invalid agent signals");
  return r.signals.map((entry) => {
    const s = obj(entry, "agent signal");
    const id = text(s.id, "signal id");
    if (!UUID_RE.test(id)) fail("Invalid signal id");
    return {
      id,
      language_code: text(s.language_code, "signal language"),
      kind: oneOf(s.kind, ["topic", "goal", "error_type", "pace", "turn_length"] as const, "signal kind"),
      code: text(s.code, "signal code"),
      usage_count: int(s.usage_count, "signal count"),
    };
  });
}

// FR-3.11: the separate, default-off consent to keep spoken turns as text, and the kept turns.
export type TranscriptConsent = AgentConsent & { active: boolean };
export type TranscriptWordScore = { word: string; accuracy: number; error_type: string };
export type TranscriptGrammarError = { quote: string; suggestion: string; note: string | null; error_type: string | null };
export type KeptTranscript = {
  id: string;
  session_id: string;
  language_code: string;
  topic: string | null;
  assistance_level: number;
  agent_text: string | null;
  learner_text: string;
  recognized_text: string | null;
  word_scores: TranscriptWordScore[];
  grammar_errors: TranscriptGrammarError[];
  occurred_at: string;
};
export type TranscriptPage = { transcripts: KeptTranscript[]; next_before: string | null };

export function parseTranscriptConsent(raw: unknown): TranscriptConsent {
  const r = obj(raw, "transcript consent");
  if (typeof r.active !== "boolean") fail("Invalid transcript consent");
  return { ...parseAgentConsent(raw), active: r.active };
}

function list(value: unknown, what: string): unknown[] {
  if (!Array.isArray(value)) fail(`Invalid ${what}`);
  return value;
}

export function parseTranscriptPage(raw: unknown): TranscriptPage {
  const r = obj(raw, "transcripts");
  return {
    next_before: nullableText(r.next_before, "transcript cursor"),
    transcripts: list(r.transcripts, "transcripts").map((entry) => {
      const t = obj(entry, "transcript");
      const id = text(t.id, "transcript id");
      if (!UUID_RE.test(id)) fail("Invalid transcript id");
      return {
        id,
        session_id: text(t.session_id, "transcript session"),
        language_code: text(t.language_code, "transcript language"),
        topic: nullableText(t.topic, "transcript topic"),
        assistance_level: int(t.assistance_level, "assistance level"),
        agent_text: nullableText(t.agent_text, "agent turn"),
        learner_text: text(t.learner_text, "learner turn"),
        recognized_text: nullableText(t.recognized_text, "recognized text"),
        word_scores: list(t.word_scores, "word scores").map((value) => {
          const w = obj(value, "word score");
          if (typeof w.accuracy !== "number" || !Number.isFinite(w.accuracy)) fail("Invalid word score");
          return { word: text(w.word, "scored word"), accuracy: w.accuracy, error_type: text(w.error_type, "word error") };
        }),
        grammar_errors: list(t.grammar_errors, "grammar errors").map((value) => {
          const g = obj(value, "grammar error");
          return {
            quote: text(g.quote, "error quote"),
            suggestion: text(g.suggestion, "error suggestion"),
            note: nullableText(g.note, "error note"),
            error_type: nullableText(g.error_type, "error type"),
          };
        }),
        occurred_at: text(t.occurred_at, "transcript time"),
      };
    }),
  };
}

// What the agent remembers about the learner across conversations: short notes the learner can read and delete.
export type AgentMemoryKind = "goal" | "interest" | "error" | "follow_up";
export type AgentMemoryItem = { id: string; kind: AgentMemoryKind; text: string; language_code: string | null; created_at: string };

/** A malformed note is dropped; a response that is not `{ items: [...] }` is an error. */
export function parseAgentMemory(raw: unknown): AgentMemoryItem[] {
  const r = obj(raw, "agent memory");
  if (!Array.isArray(r.items)) fail("Invalid agent memory");
  const notes: AgentMemoryItem[] = [];
  for (const entry of r.items) {
    try {
      const m = obj(entry, "memory note");
      const created = text(m.created_at, "memory time");
      if (Number.isNaN(Date.parse(created))) fail("Invalid memory time");
      notes.push({
        id: text(m.id, "memory id"),
        kind: oneOf(m.kind, ["goal", "interest", "error", "follow_up"] as const, "memory kind"),
        text: text(m.text, "memory text"),
        language_code: nullableText(m.language_code, "memory language"),
        created_at: created,
      });
    } catch {
      // Dropped: one bad note must not hide the rest.
    }
  }
  return notes;
}

/** Practice Tata asked for again, as the agent screen lists it (`title` is null when the item no longer exists). */
export type AgentStudyRequest = { id: string; kind: "grammar_redo" | "word_review"; title: string | null; reason: string | null };

/** Kinds the screen cannot show are dropped, as is a malformed row; a response that is not `{ items: [...] }` is an error. */
export function parseAgentStudyRequests(raw: unknown): AgentStudyRequest[] {
  const r = obj(raw, "study requests");
  if (!Array.isArray(r.items)) fail("Invalid study requests");
  const found: AgentStudyRequest[] = [];
  for (const entry of r.items) {
    try {
      const item = obj(entry, "study request");
      found.push({
        id: text(item.id, "study request id"),
        kind: oneOf(item.kind, ["grammar_redo", "word_review"] as const, "study request kind"),
        title: nullableText(item.title, "study request title"),
        reason: nullableText(item.reason, "study request reason"),
      });
    } catch {
      // Dropped: one row the screen cannot show must not hide the rest.
    }
  }
  return found;
}
