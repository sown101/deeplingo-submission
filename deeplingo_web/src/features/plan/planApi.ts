import type { ApiClient } from "../../lib/api/apiClient";
import { localUtcOffsetMinutes } from "../progress/progressApi";
import { parsePlanItem, parseStudyPlan, type PlanItem, type StudyPlan } from "./planModels";

// Learners send only their local date and a choice per proposal; the server composes the plan.
export class PlanApi {
  constructor(private readonly client: ApiClient) {}

  async today(day: string): Promise<StudyPlan> {
    return parseStudyPlan(await this.client.get<unknown>("/learner/me/plan", { query: { day, utc_offset_minutes: String(localUtcOffsetMinutes()) } }));
  }

  async accept(itemId: string): Promise<PlanItem> {
    return parsePlanItem(await this.client.post<unknown>(`/learner/me/plan/items/${encodeURIComponent(itemId)}/accept`, {}));
  }

  /** Reverses one change the agent made to today's tasks: `added` takes the task out, `removed` puts it back. */
  async undoEdit(itemId: string, change: "added" | "removed"): Promise<PlanItem> {
    return parsePlanItem(await this.client.post<unknown>(`/learner/me/plan/items/${encodeURIComponent(itemId)}/undo`, { change }));
  }

  async dismiss(itemId: string): Promise<PlanItem> {
    return parsePlanItem(await this.client.post<unknown>(`/learner/me/plan/items/${encodeURIComponent(itemId)}/dismiss`, {}));
  }
}
