// Realtime voice companion client. The learner's audio goes to our backend, never to a
// provider: the backend authenticates the first message, builds the context, checks every companion
// turn and the hints/corrections it shows. The client only plays audio and renders validated events.

import { parseAgentAction, type AgentAction, type CompanionEntry } from "./companionModels";
import { parseAnalysisReference, type AnalysisReference } from "./sessionAnalysisModels";
import { parsePlanItem, type PlanItem } from "../plan/planModels";
import { tr } from "../../i18n/i18n";

export interface RealtimeHint {
  /** The server's help step: 1 question and words, 2 adds a frame, 3 adds a model answer. */
  level: 1 | 2 | 3;
  question: string | null;
  frame: string | null;
  frame_reason: string | null;
  model_sentence: string | null;
  items: { id: string; text: string; meaning: string | null }[];
}

/** One thing the agent offers when the learner opens it without a topic; the label is the client's. */
export interface OpeningChoice {
  id: "video" | "words" | "roleplay" | "free";
  count: number | null;
}

/** One turn's pronunciation: an overall number and the few words that sounded wrong. */
export interface TurnPronunciation {
  turn: number;
  overall: number;
  weak_words: string[];
}

// Provider markers that are not speech ("<no speech>", "{pause}", "[silence]"); the server removes them too.
const MARKER = /<[A-Za-z_][^<>\n]{0,39}>|\{[A-Za-z_][^{}\n]{0,39}\}|\[(?:no speech|noise|silence|pause|music|applause|laughter|inaudible)\]/gi;
const OPEN_MARKER = /[<{](?:[A-Za-z_][^<>{}\n]{0,39})?$/;

/** What the learner may read: speech only, without markers (a marker still arriving is hidden as well). */
export function speechOnly(text: string): string {
  return text.replace(MARKER, "").replace(OPEN_MARKER, "");
}

export interface RealtimeSuggestion {
  sentence: string;
  explanation: string;
}

/** The rule behind the learner's sentence: an approved lesson (title, rules) or an AI-written, unchecked explanation. */
export interface GrammarExplanation {
  explanation: string;
  example: string | null;
  title?: string;
  rules?: string[];
  unverified: boolean;
}

/** Counts and word names only: no speech, no score. */
export interface SessionSummary {
  spoken_turns: number;
  corrections: number;
  hints: number;
  suggestions: number;
  words_to_reuse: string[];
  /** Words that sounded wrong in the conversation: practice feedback only, no scores. */
  weak_words?: string[];
  /** The kinds of grammar mistake made (codes like verb_tense), never the sentences. */
  error_types?: string[];
  /** A fixed short note for each kind of mistake, with an example in the learning language. */
  grammar_notes?: { code: string; note: string; example: string | null }[];
}

export interface RealtimeCorrection {
  quote: string;
  suggestion: string;
  note: string;
}

export interface RealtimeLookup {
  word: string;
  entries: {
    headword: string;
    senses: { text: string; part_of_speech: string | null }[];
    source_name: string | null;
    source_license: string | null;
    source_url: string | null;
  }[];
}

/** Practice the agent put in the learner's notebook (a corrected grammar point to redo). */
export interface StudyRequestNotice {
  kind: "grammar_redo" | "word_review";
  item: string;
  title: string | null;
}

/** A word the agent looked up that the learner may save; nothing is saved until they tap Save. */
export interface SaveWordOffer {
  word: string;
  headword: string;
  language_code: string;
  entry_id: string;
  sense_id: string;
  meaning: string | null;
}

export const OFFER_PATHS = {
  review: "/review/quick",
  grammar: "/words/lists?tab=grammar",
  notebook: "/words/lists",
} as const;
export type OfferKind = keyof typeof OFFER_PATHS;

export type RealtimeEvent =
  | { type: "ready"; max_seconds: number; topic: string; language_code: string; session_id?: string }
  | { type: "audio_format"; sample_rate: number }
  | { type: "transcript"; role: "learner" | "companion"; text: string }
  | { type: "turn_complete" }
  | { type: "choices"; items: OpeningChoice[] }
  | { type: "pronunciation"; score: TurnPronunciation }
  | { type: "tasks"; items: PlanItem[] }
  | { type: "offer"; kind: OfferKind }
  | { type: "roleplay"; title: string }
  | { type: "interrupted" }
  | { type: "hint"; hint: RealtimeHint }
  | { type: "suggestions"; items: RealtimeSuggestion[] }
  | { type: "natural"; items: RealtimeSuggestion[] }
  | { type: "grammar"; grammar: GrammarExplanation }
  | { type: "correction"; correction: RealtimeCorrection }
  | { type: "looked_up"; lookup: RealtimeLookup }
  | { type: "study_request"; request: StudyRequestNotice }
  | { type: "save_word"; offer: SaveWordOffer }
  | { type: "action"; card: AgentAction }
  | { type: "ended"; reason: string; follow_ups: PlanItem[]; analysis?: AnalysisReference;
      summary?: SessionSummary }
  | { type: "error"; code: string; message: string };

const str = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);
const count = (value: unknown): number | null =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 1000 ? value : null;
const HTTPS = /^https:\/\/[^\s"'<>]+$/;

/** Server JSON -> a typed event, or null for anything malformed or unknown (ignored, never rendered). */
export function parseRealtimeEvent(raw: string): RealtimeEvent | null {
  let message: Record<string, unknown>;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    message = value as Record<string, unknown>;
  } catch {
    return null;
  }
  switch (message.type) {
    case "ready":
      return typeof message.max_seconds === "number" && str(message.topic) && str(message.language_code)
        ? { type: "ready", max_seconds: message.max_seconds, topic: message.topic as string,
            language_code: message.language_code as string,
            ...(str(message.session_id) ? { session_id: message.session_id as string } : {}) }
        : null;
    case "audio_format":
      return typeof message.sample_rate === "number" && message.sample_rate >= 8000 && message.sample_rate <= 48000
        ? { type: "audio_format", sample_rate: message.sample_rate } : null;
    case "transcript":
      return (message.role === "learner" || message.role === "companion") && typeof message.text === "string"
        ? { type: "transcript", role: message.role, text: message.text } : null;
    case "turn_complete":
    case "interrupted":
      return { type: message.type };
    case "choices": {
      const ids = ["video", "words", "roleplay", "free"];
      const items = (Array.isArray(message.items) ? message.items : []).flatMap((item) => {
        const row = (item ?? {}) as Record<string, unknown>;
        const id = typeof row.id === "string" && ids.includes(row.id) ? row.id as OpeningChoice["id"] : null;
        return id ? [{ id, count: count(row.count) }] : [];
      }).slice(0, 4);
      return items.length > 0 ? { type: "choices", items } : null;
    }
    case "pronunciation": {
      const [turn, overall] = [count(message.turn), count(message.overall)];
      const weak = (Array.isArray(message.weak_words) ? message.weak_words : [])
        .filter((word): word is string => typeof word === "string" && word.trim() !== "" && word.length <= 60).slice(0, 3);
      return turn !== null && overall !== null && overall <= 100
        ? { type: "pronunciation", score: { turn, overall, weak_words: weak } } : null;
    }
    case "tasks":
      try {
        return { type: "tasks", items: Array.isArray(message.items) ? message.items.map(parsePlanItem) : [] };
      } catch {
        return null;
      }
    case "offer":
      return typeof message.kind === "string" && message.kind in OFFER_PATHS ? { type: "offer", kind: message.kind as OfferKind } : null;
    case "roleplay":
      return str(message.title) ? { type: "roleplay", title: str(message.title)! } : null;
    case "hint": {
      const items = Array.isArray(message.items) ? message.items : [];
      return {
        type: "hint",
        hint: {
          level: message.level === 2 || message.level === 3 ? message.level : 1,
          question: str(message.question), frame: str(message.frame), frame_reason: str(message.frame_reason),
          model_sentence: str(message.model_sentence),
          items: items.flatMap((item) => {
            const row = item as Record<string, unknown>;
            const id = str(row?.id);
            const text = str(row?.text);
            return id && text ? [{ id, text, meaning: str(row.meaning) }] : [];
          }),
        },
      };
    }
    case "suggestions":
    case "natural": {
      const items = (Array.isArray(message.items) ? message.items : []).flatMap((item) => {
        const row = item as Record<string, unknown>;
        const sentence = str(row?.sentence);
        const explanation = str(row?.explanation);
        return sentence && explanation ? [{ sentence, explanation }] : [];
      }).slice(0, 3);
      return items.length > 0 ? { type: message.type, items } : null;
    }
    case "grammar": {
      const explanation = str(message.explanation);
      const example = str(message.example);
      // Only an explicit `false` marks the owner's approved lesson; anything else is AI-written and labelled so.
      const unverified = message.unverified !== false;
      const title = str(message.title);
      const rules = (Array.isArray(message.rules) ? message.rules : [])
        .flatMap((rule) => typeof rule === "string" && rule.trim() && rule.length <= 200 ? [rule] : []).slice(0, 4);
      return explanation && explanation.length <= (unverified ? 600 : 2000) && (example === null || example.length <= 300)
        ? { type: "grammar", grammar: { explanation, example, unverified,
          ...(title && title.length <= 200 ? { title } : {}), ...(rules.length ? { rules } : {}) } } : null;
    }
    case "correction": {
      const quote = str(message.quote);
      const suggestion = str(message.suggestion);
      const note = str(message.note);
      return quote && suggestion && note ? { type: "correction", correction: { quote, suggestion, note } } : null;
    }
    case "looked_up": {
      const word = str(message.word);
      if (!word || !Array.isArray(message.entries)) return null;
      const entries = message.entries.flatMap((entry) => {
        const row = entry as Record<string, unknown>;
        const headword = str(row?.headword);
        const senses = Array.isArray(row?.senses) ? row.senses.flatMap((sense) => {
          const s = sense as Record<string, unknown>;
          const text = str(s?.text);
          return text ? [{ text, part_of_speech: str(s.part_of_speech) }] : [];
        }) : [];
        const url = str(row?.source_url);
        return headword && senses.length > 0 ? [{
          headword, senses, source_name: str(row.source_name), source_license: str(row.source_license),
          source_url: url && HTTPS.test(url) ? url : null,
        }] : [];
      });
      return entries.length > 0 ? { type: "looked_up", lookup: { word, entries } } : null;
    }
    case "study_request": {
      const item = str(message.item);
      return (message.kind === "grammar_redo" || message.kind === "word_review") && item && item.length <= 200
        ? { type: "study_request", request: { kind: message.kind, item, title: str(message.title) } } : null;
    }
    case "save_word": {
      const [word, headword, language, entry, sense] = [message.word, message.headword, message.language_code,
        message.entry_id, message.sense_id].map(str);
      return word && headword && language && entry && sense
        ? { type: "save_word", offer: { word, headword, language_code: language, entry_id: entry, sense_id: sense,
            meaning: str(message.meaning) } } : null;
    }
    case "action": {
      const card = parseAgentAction(message);
      return card ? { type: "action", card } : null;
    }
    case "ended": {
      let followUps: PlanItem[] = [];
      try {
        followUps = Array.isArray(message.follow_ups) ? message.follow_ups.map(parsePlanItem) : [];
      } catch {
        followUps = [];
      }
      const summary = parseSummary(message.summary);
      return { type: "ended", reason: str(message.reason) ?? "ended",
               follow_ups: followUps, ...(summary ? { summary } : {}),
               ...(parseAnalysisReference(message.analysis) ? { analysis: parseAnalysisReference(message.analysis)! } : {}) };
    }
    case "error":
      return { type: "error", code: str(message.code) ?? "realtime_error",
               message: str(message.message) ?? tr("Something went wrong.") };
    default:
      return null;
  }
}

function parseSummary(raw: unknown): SessionSummary | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const [spoken, corrections, hints, suggestions] = ["spoken_turns", "corrections", "hints", "suggestions"]
    .map((key) => count(row[key]));
  const words = Array.isArray(row.words_to_reuse) ? row.words_to_reuse : null;
  if (spoken === null || corrections === null || hints === null || suggestions === null || !words) return null;
  const names = (list: unknown[]) =>
    list.flatMap((word) => (typeof word === "string" && word.trim() && word.length <= 60 ? [word] : []));
  const weak = Array.isArray(row.weak_words) ? names(row.weak_words).slice(0, 6) : [];
  const kinds = Array.isArray(row.error_types)
    ? row.error_types.filter((kind): kind is string => typeof kind === "string" && /^[a-z_]{1,32}$/.test(kind)).slice(0, 6) : [];
  const notes = (Array.isArray(row.grammar_notes) ? row.grammar_notes : []).flatMap((entry) => {
    const n = (entry ?? {}) as Record<string, unknown>;
    const note = typeof n.note === "string" ? n.note.trim() : "";
    const example = typeof n.example === "string" && n.example.trim() && n.example.length <= 120 ? n.example : null;
    return typeof n.code === "string" && /^[a-z_]{1,32}$/.test(n.code) && note && note.length <= 300
      ? [{ code: n.code, note, example }] : [];
  }).slice(0, 3);
  return { spoken_turns: spoken, corrections, hints, suggestions, words_to_reuse: names(words).slice(0, 6),
           ...(weak.length > 0 ? { weak_words: weak } : {}), ...(kinds.length > 0 ? { error_types: kinds } : {}),
           ...(notes.length > 0 ? { grammar_notes: notes } : {}) };
}

export function realtimeUrl(apiBaseUrl: string): string {
  const url = new URL(`${apiBaseUrl.replace(/\/+$/, "")}/learner/me/companion/realtime`, window.location.origin);
  url.protocol = url.protocol === "http:" ? "ws:" : "wss:";
  return url.toString();
}

export interface RealtimeHandlers {
  onEvent(event: RealtimeEvent): void;
  onAudio(samples: Int16Array): void;
  onClosed(code: number): void;
}

const MAX_FRAME_SAMPLES = 16_000; // the server accepts at most one second per frame
// A dropped socket is replaced within the server's grace period (8 s): these waits, then the conversation ends.
const REATTACH_DELAYS_MS = [300, 1000, 2000];

export class RealtimeSession {
  private socket: WebSocket | null = null;
  private token = "";
  private sessionId: string | null = null;
  /** JSON events received; the server numbers what it sends the same way, so a new socket asks for the rest. */
  private received = 0;
  private finished = false;
  private reattaches = 0;

  constructor(private readonly url: string, private readonly handlers: RealtimeHandlers) {}

  open(token: string, start: { entry: CompanionEntry; library_item_id: string | null; day: string; topic_id?: string; segment_id?: string; scenario_id?: string; swap_roles?: boolean }): void {
    this.token = token;
    this.connect(() => ({ type: "start", entry: start.entry, day: start.day,
      ...(start.entry === "video" && start.library_item_id ? { library_item_id: start.library_item_id } : {}),
      ...(start.topic_id ? { topic_id: start.topic_id } : {}),
      ...(start.segment_id ? { segment_id: start.segment_id } : {}),
      ...(start.scenario_id ? { scenario_id: start.scenario_id, swap_roles: start.swap_roles ?? false } : {}),
    }));
  }

  private connect(first: () => Record<string, unknown>): void {
    const socket = new WebSocket(this.url);
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onopen = () => {
      // The token goes in the first message, never in the URL (URLs reach logs).
      socket.send(JSON.stringify({ type: "auth", token: this.token }));
      socket.send(JSON.stringify(first()));
    };
    socket.onmessage = (message: MessageEvent) => {
      if (message.data instanceof ArrayBuffer) {
        if (message.data.byteLength % 2 === 0) this.handlers.onAudio(new Int16Array(message.data));
        return;
      }
      if (typeof message.data === "string") {
        this.received += 1;
        this.reattaches = 0; // the new socket works
        const event = parseRealtimeEvent(message.data);
        if (event?.type === "ready" && event.session_id) this.sessionId = event.session_id;
        if (event?.type === "ended" || event?.type === "error") this.finished = true;
        if (event) this.handlers.onEvent(event);
      }
    };
    socket.onclose = (event: CloseEvent) => {
      if (this.socket !== socket) return; // an old socket closing after its replacement opened
      this.socket = null;
      if (this.shouldReattach(event.code)) {
        const delay = REATTACH_DELAYS_MS[this.reattaches++];
        setTimeout(() => {
          if (!this.finished) this.connect(() => ({ type: "resume", session_id: this.sessionId, last_seq: this.received }));
        }, delay);
        return;
      }
      this.handlers.onClosed(event.code);
    };
  }

  /** A socket that dropped by itself (not ended, refused or closed by the learner) is replaced while it can be. */
  private shouldReattach(code: number): boolean {
    return !this.finished && this.sessionId !== null && code !== 1000 && code < 4000
      && this.reattaches < REATTACH_DELAYS_MS.length;
  }

  sendAudio(samples: Int16Array): void {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    for (let offset = 0; offset < samples.length; offset += MAX_FRAME_SAMPLES) {
      const frame = samples.slice(offset, offset + MAX_FRAME_SAMPLES);
      socket.send(frame.buffer);
    }
  }

  help(): void {
    this.sendControl("help");
  }

  /** The learner asked why: the rule behind their last sentence. */
  explain(): void {
    this.sendControl("explain");
  }

  /** The learner asked for more natural ways to say their last sentence. */
  natural(): void {
    this.sendControl("natural");
  }

  /** The learner asked for ideas of what to say. */
  suggest(): void {
    this.sendControl("suggest");
  }

  /** The learner tapped one of the opening choices. */
  choose(id: OpeningChoice["id"]): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: "choose", id }));
  }

  end(): void {
    this.sendControl("end");
  }

  close(): void {
    this.finished = true;
    this.socket?.close(1000);
    this.socket = null;
  }

  private sendControl(type: "help" | "suggest" | "explain" | "natural" | "end"): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type }));
  }
}
