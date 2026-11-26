export type ApiErrorKind =
  | "unauthorized"
  | "validation"
  | "not_found"
  | "conflict"
  | "server"
  | "network"
  | "timeout"
  | "parse"
  | "ambiguous";

export interface ApiErrorDetail {
  code?: string;
  message?: string;
  raw?: unknown;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly detail: ApiErrorDetail;

  constructor(kind: ApiErrorKind, status: number | null, detail: ApiErrorDetail) {
    // HTTP `detail` may contain operational diagnostics. Keep Error.message
    // learner-safe so accidental rendering cannot expose server internals;
    // feature workflows use status/kind/code to choose contextual copy.
    super(safeMessage(kind));
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

function safeMessage(kind: ApiErrorKind): string {
  switch (kind) {
    case "unauthorized": return "Authentication is required.";
    case "validation": return "The request could not be processed.";
    case "not_found": return "The requested item was not found.";
    case "conflict": return "The request conflicts with current server state.";
    case "server": return "The service is temporarily unavailable.";
    case "network": return "The server could not be reached.";
    case "timeout": return "The request timed out.";
    case "parse": return "The server response could not be read.";
    case "ambiguous": return "The request outcome could not be confirmed.";
  }
}

export function detailFromResponse(body: unknown): ApiErrorDetail {
  if (body && typeof body === "object") {
    const obj = body as Record<string, unknown>;
    const nested = obj.detail;
    if (typeof nested === "string") return { message: nested, raw: body };
    if (nested && typeof nested === "object") {
      const d = nested as Record<string, unknown>;
      return {
        code: typeof d.code === "string" ? d.code : undefined,
        message: typeof d.message === "string" ? d.message : undefined,
        raw: body,
      };
    }
    return { raw: body };
  }
  return { raw: body };
}

export function isRetryable(error: ApiError): boolean {
  return error.kind === "network" || error.kind === "timeout" || error.kind === "server";
}
