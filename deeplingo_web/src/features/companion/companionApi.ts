import type { ApiClient } from "../../lib/api/apiClient";
import { ApiError } from "../../lib/api/errors";
import { encodeWav } from "../../lib/audio/wav";
import {
  parseAgentConsent,
  parseAgentSignals,
  parseAgentMemory,
  parseAgentStudyRequests,
  parseTranscriptConsent,
  parseTranscriptPage,
  parseCompanionAudio,
  parseCompanionTurn,
  parseCompanionFeedback,
  parseRoleplayScenarios,
  type CompanionFeedback,
  type AgentConsent,
  type AgentSignal,
  type AgentMemoryItem,
  type AgentStudyRequest,
  type CompanionEntry,
  type CompanionRequest,
  type CompanionTurn,
  type TranscriptConsent,
  type TranscriptPage,
} from "./companionModels";
import { localDay } from "../plan/planModels";

// Transcription, the model turn and speech synthesis run in one request (on /turns/stream the speech follows the
// turn sentence by sentence, so the reply is shown and starts playing sooner).
const TURN_TIMEOUT_MS = 45_000;

// Learners send only an entry point, selectors, the signed session ticket and raw
// audio; the backend builds the conversation context.
/** One part of a reply's speech, in order, as it is synthesised. */
export type OnReplyAudio = (audio: { mime_type: string; base64: string }, index: number) => void;

export class CompanionApi {
  constructor(private readonly client: ApiClient) {}

  private async send(form: FormData, onAudio?: OnReplyAudio): Promise<CompanionTurn> {
    if (!onAudio) {
      return parseCompanionTurn(
        await this.client.postForm<unknown>("/learner/me/companion/turns", form, { timeoutMs: TURN_TIMEOUT_MS }),
      );
    }
    // The turn arrives as soon as the agent answered; its speech follows. Errors before it reject as on /turns.
    return new Promise<CompanionTurn>((resolve, reject) => {
      let turn: CompanionTurn | null = null;
      this.client.postFormLines("/learner/me/companion/turns/stream", form, (line) => {
        const row = (line ?? {}) as Record<string, unknown>;
        if (row.type === "turn" && turn === null) {
          try {
            turn = parseCompanionTurn(row.turn);
            resolve(turn);
          } catch (error) {
            reject(error);
          }
        } else if (row.type === "audio" && turn !== null) {
          const audio = parseCompanionAudio(row.audio);
          if (audio && typeof row.index === "number") onAudio(audio, row.index);
        }
      }, { timeoutMs: TURN_TIMEOUT_MS }).then(
        () => { if (turn === null) reject(new ApiError("parse", 200, { message: "No turn in the stream" })); },
        (error: unknown) => { if (turn === null) reject(error); },
      );
    });
  }

  async scenarios() { return parseRoleplayScenarios(await this.client.get<unknown>("/learner/me/companion/scenarios")); }

  async start(entry: CompanionEntry, libraryItemId: string | null, context?: { segment_id?: string; topic_id?: string; scenario_id?: string; swap_roles?: boolean; text_only?: boolean }): Promise<CompanionTurn> {
    const body = entry === "video" && libraryItemId ? { entry, library_item_id: libraryItemId } : { entry };
    return parseCompanionTurn(
      await this.client.post<unknown>("/learner/me/companion/sessions", { ...body, ...context }, { timeoutMs: TURN_TIMEOUT_MS }),
    );
  }

  async turn(sessionTicket: string, samples: Int16Array, onAudio?: OnReplyAudio): Promise<CompanionTurn> {
    const form = new FormData();
    form.append("session_ticket", sessionTicket);
    form.append("audio", encodeWav(samples), "turn.wav");
    // Names today's plan, so a closing turn can add next steps to it.
    form.append("day", localDay());
    return this.send(form, onAudio);
  }

  /** Send a typed turn in either conversation mode. */
  async turnText(sessionTicket: string, text: string, onAudio?: OnReplyAudio): Promise<CompanionTurn> {
    const form = new FormData();
    form.append("session_ticket", sessionTicket);
    form.append("text", text);
    form.append("day", localDay());
    return this.send(form, onAudio);
  }

  /** A help button in the text conversation (hint, explain, natural, suggest), with the learner's words or without. */
  async turnRequest(sessionTicket: string, request: CompanionRequest, text?: string, onAudio?: OnReplyAudio): Promise<CompanionTurn> {
    const form = new FormData();
    form.append("session_ticket", sessionTicket);
    form.append("request", request);
    if (text) form.append("text", text);
    form.append("day", localDay());
    return this.send(form, onAudio);
  }

  /** The learner left: the server closes the conversation and adds its follow-ups to today's plan. */
  async finish(sessionTicket: string): Promise<CompanionFeedback> {
    const form = new FormData();
    form.append("session_ticket", sessionTicket);
    form.append("day", localDay());
    return parseCompanionFeedback(await this.client.postForm<unknown>("/learner/me/companion/finish", form, { timeoutMs: TURN_TIMEOUT_MS }));
  }

  async getAgentConsent(): Promise<AgentConsent> {
    return parseAgentConsent(await this.client.get<unknown>("/learner/me/agent/consent"));
  }

  /** One consent for every voice conversation; the learner can revoke it at any time. */
  async setAgentConsent(granted: boolean): Promise<AgentConsent> {
    return parseAgentConsent(await this.client.put<unknown>("/learner/me/agent/consent", { granted }));
  }

  async getAgentSignals(): Promise<AgentSignal[]> {
    return parseAgentSignals(await this.client.get<unknown>("/learner/me/agent/signals"));
  }

  async deleteAgentSignal(signalId: string): Promise<void> {
    await this.client.request<unknown>("DELETE", `/learner/me/agent/signals/${encodeURIComponent(signalId)}`);
  }

  async deleteAllAgentSignals(): Promise<void> {
    await this.client.request<unknown>("DELETE", "/learner/me/agent/signals");
  }

  /** What the agent remembers across conversations (goals, interests, recurring mistakes, promises). */
  async getAgentMemory(): Promise<AgentMemoryItem[]> {
    return parseAgentMemory(await this.client.get<unknown>("/learner/me/agent/memory"));
  }

  async deleteAgentMemoryItem(memoryId: string): Promise<void> {
    await this.client.request<unknown>("DELETE", `/learner/me/agent/memory/${encodeURIComponent(memoryId)}`);
  }

  async deleteAllAgentMemory(): Promise<void> {
    await this.client.request<unknown>("DELETE", "/learner/me/agent/memory");
  }

  /** Practice Tata asked for again in this language, open only. */
  async getStudyRequests(language: string, support: string): Promise<AgentStudyRequest[]> {
    const query = new URLSearchParams({ language, support });
    return parseAgentStudyRequests(await this.client.get<unknown>(`/learner/me/agent/study-requests?${query}`));
  }

  async dismissStudyRequest(requestId: string): Promise<void> {
    await this.client.request<unknown>("POST", `/learner/me/study-requests/${encodeURIComponent(requestId)}/dismiss`);
  }

  /** FR-3.11: a second consent, separate from voice, to keep spoken turns as text. Off until the learner allows it. */
  async getTranscriptConsent(): Promise<TranscriptConsent> {
    return parseTranscriptConsent(await this.client.get<unknown>("/learner/me/agent/transcripts/consent"));
  }

  async setTranscriptConsent(granted: boolean): Promise<TranscriptConsent> {
    return parseTranscriptConsent(await this.client.put<unknown>("/learner/me/agent/transcripts/consent", { granted }));
  }

  async getTranscripts(before?: string | null): Promise<TranscriptPage> {
    const query = before ? `?before=${encodeURIComponent(before)}` : "";
    return parseTranscriptPage(await this.client.get<unknown>(`/learner/me/agent/transcripts${query}`));
  }

  async deleteTranscript(transcriptId: string): Promise<void> {
    await this.client.request<unknown>("DELETE", `/learner/me/agent/transcripts/${encodeURIComponent(transcriptId)}`);
  }

  async deleteAllTranscripts(): Promise<void> {
    await this.client.request<unknown>("DELETE", "/learner/me/agent/transcripts");
  }
}
