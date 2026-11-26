import type { ApiClient } from "../../lib/api/apiClient";
import { parseCoverageSummaries, type CoverageSummary } from "./coverageModels";

// The learner sends only a Library item id; the server resolves ownership, the transcript's word
// profile and the learner's own level and words.
export class CoverageApi {
  constructor(private readonly client: ApiClient) {}

  // The learner's videos, comfortable ones first. A few videos without a profile are profiled per call.
  async forLibrary(): Promise<CoverageSummary[]> {
    return parseCoverageSummaries(await this.client.get<unknown>("/learner/me/video-coverage"));
  }
}
