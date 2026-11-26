import type { ApiClient } from "../../lib/api/apiClient";
import { ApiError } from "../../lib/api/errors";
import type {
  LearnerVideoImportResponse,
  LibraryVideoDetail,
  LibraryVideoSummary,
} from "../../lib/api/dto";
import { parseLibraryVideoDetail, parseLibraryVideoSummary } from "./libraryModels";

export class LibraryApi {
  constructor(private readonly client: ApiClient) {}

  async listVideos(): Promise<LibraryVideoSummary[]> {
    const raw = await this.client.get<unknown>("/learner/me/library/videos");
    return parseLibraryVideoSummaryList(raw);
  }

  async getVideo(libraryItemId: string): Promise<LibraryVideoDetail> {
    const raw = await this.client.get<unknown>(
      `/learner/me/library/videos/${libraryItemId}`,
    );
    return parseLibraryVideoDetail(raw);
  }

  async importVideo(url: string): Promise<LearnerVideoImportResponse> {
    const raw = await this.client.post<unknown>("/learner/me/library/videos", { url });
    return parseImportResponse(raw);
  }

  async retryVideo(libraryItemId: string): Promise<LearnerVideoImportResponse> {
    const raw = await this.client.post<unknown>(
      `/learner/me/library/videos/${libraryItemId}/retry`,
    );
    return parseImportResponse(raw);
  }

  async retryLearning(libraryItemId: string): Promise<LearnerVideoImportResponse> {
    const raw = await this.client.post<unknown>(
      `/learner/me/library/videos/${libraryItemId}/learning/retry`,
    );
    return parseImportResponse(raw);
  }
}

export function parseLibraryVideoSummaryList(raw: unknown): LibraryVideoSummary[] {
  if (!Array.isArray(raw)) {
    throw new ApiError("parse", null, { message: "Invalid library list response" });
  }
  return raw.map((item) => parseLibraryVideoSummary(item));
}

export function parseImportResponse(raw: unknown): LearnerVideoImportResponse {
  const record = expectObject(raw, "Invalid import response");
  const item = parseLibraryVideoDetail(record.item);
  const commandStatus = typeof record.command_status === "string" ? record.command_status : null;
  if (!commandStatus) {
    throw new ApiError("parse", null, { message: "Invalid import command status" });
  }
  return { command_status: commandStatus, item };
}

function expectObject(value: unknown, message: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError("parse", null, { message });
  }
  return value as Record<string, unknown>;
}
