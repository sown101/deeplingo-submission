import type { ApiClient } from "../../lib/api/apiClient";
import { ApiError } from "../../lib/api/errors";
import { parseGrammarView, type GrammarScope, type GrammarView } from "./grammar/grammarModels";
import type { ConceptInteractionView, PlayableVideo, VideoTranscriptView, WordLookupView } from "../../lib/api/dto";
import {
  parseConceptInteractionView,
  parsePlayableVideo,
  parseVideoTranscriptView,
  parseWordLookupView,
} from "./videoModels";
import { parseVideoWorkspace, type VideoWorkspaceView } from "./workspace/workspaceModels";
import { parseRegionResult, type RegionResult } from "./workspace/regionResult";
import { parseVideoParts, type VideoParts } from "./workspace/videoParts";
import {
  parseQuestionAnswer,
  parseRegionQuestions,
  type QuestionAnswer,
  type RegionQuestionsView,
} from "./questions/questionModels";

export class PlaybackApi {
  constructor(private readonly client: ApiClient) {}

  async explainGrammar(libraryItemId: string, segmentId: string, span: { start: number; end: number }, scope: GrammarScope): Promise<GrammarView> {
    return parseGrammarView(await this.client.post<unknown>(`/learner/me/library/videos/${libraryItemId}/grammar-explanations`, {
      segment_id: segmentId, start_codepoint: span.start, end_codepoint: span.end, scope,
    }), segmentId, scope);
  }

  async getPlayableVideo(libraryItemId: string): Promise<PlayableVideo> {
    return parsePlayableVideo(
      await this.client.get<unknown>(`/learner/me/library/videos/${libraryItemId}/playback`),
    );
  }

  async getTranscript(libraryItemId: string): Promise<VideoTranscriptView> {
    return parseVideoTranscriptView(
      await this.client.get<unknown>(`/learner/me/library/videos/${libraryItemId}/transcript`),
    );
  }

  // Meaning of any span the learner selects; the server derives the text from the segment.
  async lookup(
    libraryItemId: string,
    segment: { segment_id: string; text: string },
    span: { start: number; end: number },
  ): Promise<WordLookupView> {
    return parseWordLookupView(
      await this.client.post<unknown>(`/learner/me/library/videos/${libraryItemId}/lookup`, {
        segment_id: segment.segment_id,
        start_codepoint: span.start,
        end_codepoint: span.end,
      }),
      segment.text,
    );
  }

  // M1 S1: saved watch position and study region of this Library item.
  async getWorkspace(libraryItemId: string): Promise<VideoWorkspaceView> {
    return parseVideoWorkspace(
      await this.client.get<unknown>(`/learner/me/library/videos/${libraryItemId}/workspace`),
      libraryItemId,
    );
  }

  // A resume point only; the server bounds it to the video and never treats it as progress.
  async saveWatchPosition(libraryItemId: string, positionMs: number, options: { keepalive?: boolean } = {}): Promise<VideoWorkspaceView> {
    return parseVideoWorkspace(
      await this.client.put<unknown>(
        `/learner/me/library/videos/${libraryItemId}/workspace/position`,
        { position_ms: Math.max(0, Math.round(positionMs)) },
        { keepalive: options.keepalive },
      ),
      libraryItemId,
    );
  }

  // Segment IDs select the range; the server checks them against its current transcript.
  async saveStudyRegion(libraryItemId: string, startSegmentId: string, endSegmentId: string): Promise<VideoWorkspaceView> {
    return parseVideoWorkspace(
      await this.client.put<unknown>(`/learner/me/library/videos/${libraryItemId}/workspace/region`, {
        start_segment_id: startSegmentId,
        end_segment_id: endSegmentId,
      }),
      libraryItemId,
    );
  }

  // M1 S4 practice log. Selectors and the raw answer only: the server re-checks the answer against
  // its transcript and keeps a summary. Never a score, Attempt or Evidence. `id` makes a retry safe.
  async recordDictation(
    libraryItemId: string,
    event: { id: string; segment_id: string; level: "easy" | "hard"; answer: string; hint_shown: boolean; region_id?: string },
  ): Promise<void> {
    await this.client.post<unknown>(`/learner/me/library/videos/${libraryItemId}/practice-events/dictation`, {
      ...event,
      answer: event.answer.slice(0, 600),
    });
  }

  async recordLookup(libraryItemId: string, event: { id: string; segment_id: string; span: { start: number; end: number }; region_id?: string }): Promise<void> {
    await this.client.post<unknown>(`/learner/me/library/videos/${libraryItemId}/practice-events/lookup`, {
      id: event.id,
      segment_id: event.segment_id,
      start_codepoint: event.span.start,
      end_codepoint: event.span.end,
      region_id: event.region_id,
    });
  }

  // M1 S6: questions about the current study part, without their answers.
  async getRegionQuestions(libraryItemId: string): Promise<RegionQuestionsView> {
    return parseRegionQuestions(
      await this.client.get<unknown>(`/learner/me/library/videos/${libraryItemId}/region-questions`),
    );
  }

  // Only the chosen option: the server checks it and keeps it as practice. `id` makes a retry safe.
  async answerRegionQuestion(
    libraryItemId: string,
    questionId: string,
    answer: { id: string; selected_option: number },
  ): Promise<QuestionAnswer> {
    return parseQuestionAnswer(
      await this.client.post<unknown>(
        `/learner/me/library/videos/${libraryItemId}/region-questions/${questionId}/answer`,
        answer,
      ),
      questionId,
    );
  }

  // Study parts cut by AI on the server, once per transcript (the first call may take a few seconds).
  async getParts(libraryItemId: string): Promise<VideoParts> {
    return parseVideoParts(await this.client.get<unknown>(`/learner/me/library/videos/${libraryItemId}/parts`));
  }

  // What the learner did in one study part, summed by the server from their learning log.
  async getRegionResult(libraryItemId: string, regionId: string): Promise<RegionResult> {
    return parseRegionResult(
      await this.client.get<unknown>(`/learner/me/library/videos/${libraryItemId}/regions/${regionId}/result`),
      regionId,
    );
  }

  // Bilingual subtitles: the server translates the sentences once per language pair. Returns how many were added.
  async ensureTranslations(libraryItemId: string): Promise<number> {
    const raw = await this.client.post<{ translated?: unknown }>(`/learner/me/library/videos/${libraryItemId}/translations`, {});
    return typeof raw?.translated === "number" ? raw.translated : 0;
  }

  async getConcept(libraryItemId: string, learningObjectId: string): Promise<ConceptInteractionView> {
    return parseConceptInteractionView(
      await this.client.get<unknown>(
        `/learner/me/library/videos/${libraryItemId}/learning-objects/${learningObjectId}/concept`,
      ),
    );
  }
}

export function youtubeIdFromUrl(rawUrl: string): string | null {
  const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;
  let url: URL;
  try {
    url = new URL(rawUrl.trim());
  } catch {
    return null;
  }
  const host = url.hostname.replace(/^www\./, "");
  if (host === "youtu.be") {
    const id = url.pathname.slice(1).split("/")[0];
    return YOUTUBE_ID.test(id) ? id : null;
  }
  if (host.endsWith("youtube.com") || host.endsWith("youtube-nocookie.com")) {
    const v = url.searchParams.get("v");
    if (v && YOUTUBE_ID.test(v)) return v;
    const segments = url.pathname.split("/").filter(Boolean);
    const marker = segments.findIndex((s) => s === "shorts" || s === "embed" || s === "live");
    if (marker >= 0 && segments[marker + 1] && YOUTUBE_ID.test(segments[marker + 1])) {
      return segments[marker + 1];
    }
  }
  return null;
}

export { ApiError };
