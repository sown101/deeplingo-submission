import type { ApiClient } from "../../lib/api/apiClient";
import { ApiError } from "../../lib/api/errors";
import type { Language, LearnerLanguageProfile } from "../../lib/api/dto";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface LanguageSelection {
  learningLanguageCode: string;
  supportLanguageCode: string;
  declaredLevel?: string;
}

export function parseLanguages(raw: unknown): Language[] {
  if (!Array.isArray(raw)) {
    throw new ApiError("parse", null, { message: "Invalid languages response" });
  }
  return raw.map((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new ApiError("parse", null, { message: "Invalid languages response" });
    }
    const r = item as Record<string, unknown>;
    if (
      typeof r.code !== "string" || !r.code ||
      typeof r.name_en !== "string" || !r.name_en ||
      typeof r.name_native !== "string" || !r.name_native ||
      typeof r.script !== "string" || !r.script ||
      typeof r.is_active !== "boolean" ||
      typeof r.display_order !== "number" || !Number.isInteger(r.display_order)
    ) {
      throw new ApiError("parse", null, { message: "Invalid languages response" });
    }
    return {
      code: r.code,
      name_en: r.name_en,
      name_native: r.name_native,
      script: r.script,
      is_active: r.is_active,
      display_order: r.display_order,
    };
  });
}

export function parseLanguageProfile(raw: unknown): LearnerLanguageProfile {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new ApiError("parse", null, { message: "Invalid language profile response" });
  }
  const r = raw as Record<string, unknown>;
  const learningLanguage = nullableString(r.learning_language);
  const supportLanguage = nullableString(r.support_language);
  if (typeof r.is_complete !== "boolean") {
    throw new ApiError("parse", null, { message: "Invalid language profile response" });
  }
  // The level and daily limit are additive: an older server leaves them out and they stay absent here.
  const declared = r.declared_level === undefined ? undefined : nullableString(r.declared_level);
  const limit = r.daily_new_limit;
  if (limit !== undefined && (typeof limit !== "number" || !Number.isInteger(limit) || limit < 1 || limit > 50)) {
    throw new ApiError("parse", null, { message: "Invalid language profile response" });
  }
  return {
    learning_language: learningLanguage,
    support_language: supportLanguage,
    is_complete: r.is_complete,
    ...(declared !== undefined ? { declared_level: declared } : {}),
    ...(limit !== undefined ? { daily_new_limit: limit } : {}),
  };
}

// The Web does not use the returned user_id as identity. This boundary check
// only confirms the backend command receipt and its two safe skill projections
// before the subsequent authoritative language-profile read.
export function parseLearnerInitializationResponse(raw: unknown): void {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new ApiError("parse", null, { message: "Invalid learner initialization response" });
  }
  const r = raw as Record<string, unknown>;
  if (
    typeof r.user_id !== "string" || !UUID_RE.test(r.user_id) ||
    !(r.profile_status === "skipped" || r.profile_status === "created" || r.profile_status === "reused")
  ) {
    throw new ApiError("parse", null, { message: "Invalid learner initialization response" });
  }
}

function nullableString(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value === "string") return value;
  throw new ApiError("parse", null, { message: "Invalid nullable language value" });
}

export class OnboardingApi {
  constructor(private readonly client: ApiClient) {}

  async loadProfile(): Promise<LearnerLanguageProfile> {
    return parseLanguageProfile(await this.client.get<unknown>("/learner/me/language-profile"));
  }

  async loadLanguages(): Promise<Language[]> {
    return parseLanguages(await this.client.get<unknown>("/languages"));
  }

  async saveProfile(selection: LanguageSelection): Promise<LearnerLanguageProfile> {
    const initialized = await this.client.post<unknown>("/learner/me/initialize", {
      language_codes: [selection.learningLanguageCode],
      create_profile: true,
    });
    parseLearnerInitializationResponse(initialized);
    return parseLanguageProfile(
      await this.client.put<unknown>("/learner/me/language-profile", {
        learning_language: selection.learningLanguageCode,
        support_language: selection.supportLanguageCode,
        ...(selection.declaredLevel !== undefined ? { declared_level: selection.declaredLevel } : {}),
      }),
    );
  }
}
