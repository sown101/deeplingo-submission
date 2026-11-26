import type { ApiClient } from "../../lib/api/apiClient";
import { encodeWav } from "../../lib/audio/wav";
import {
  parseShadowingAssessment,
  type ShadowingAssessment,
} from "./speakingModels";

const AUDIO_TIMEOUT_MS = 45_000;

// Learners send only selectors and raw audio; the backend chooses references,
// grades pronunciation and returns non-evidential practice feedback.
export class SpeakingApi {
  constructor(private readonly client: ApiClient) {}

  async assessShadowing(libraryItemId: string, segmentId: string, samples: Int16Array, regionId?: string): Promise<ShadowingAssessment> {
    const form = new FormData();
    form.append("segment_id", segmentId);
    if (regionId) form.append("region_id", regionId);
    form.append("audio", encodeWav(samples), "attempt.wav");
    return parseShadowingAssessment(
      await this.client.postForm<unknown>(
        `/learner/me/library/videos/${encodeURIComponent(libraryItemId)}/shadowing/assessments`,
        form,
        { timeoutMs: AUDIO_TIMEOUT_MS },
      ),
      segmentId,
    );
  }
}
