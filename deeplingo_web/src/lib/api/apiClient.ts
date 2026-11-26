import { ApiError, detailFromResponse } from "./errors";
import type { AuthGateway } from "../auth/authGateway";

export type ApiMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  method?: ApiMethod;
  body?: unknown;
  /** Multipart body; the browser sets the boundary Content-Type. */
  form?: FormData;
  query?: Record<string, string>;
  timeoutMs?: number;
  signal?: AbortSignal;
  /** Lets a small save finish while the page unloads (fetch keepalive). */
  keepalive?: boolean;
  /** Return a successful response as a Blob, such as word audio. */
  blob?: boolean;
  /** Read a successful NDJSON response line by line as it arrives (each line parsed as JSON). */
  onLine?: (line: unknown) => void;
}

export interface ApiClientOptions {
  baseUrl: string;
  authGateway: AuthGateway;
  onUnauthorized?: () => void;
  requestScope?: RequestScope;
}

// Local lifecycle fencing only. The principal is never serialized to the server.
export interface RequestScope {
  principalId: string;
  signal: AbortSignal;
}

const DEFAULT_TIMEOUT_MS = 20_000;

export class ApiClient {
  private readonly baseUrl: string;
  private readonly auth: AuthGateway;
  private readonly onUnauthorized?: () => void;
  private readonly requestScope?: RequestScope;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.auth = options.authGateway;
    this.onUnauthorized = options.onUnauthorized;
    this.requestScope = options.requestScope;
  }

  get<T>(path: string, options: RequestOptions = {}): Promise<T> {
    return this.request<T>("GET", path, options);
  }
  post<T>(path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
    return this.request<T>("POST", path, { ...options, body });
  }
  put<T>(path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
    return this.request<T>("PUT", path, { ...options, body });
  }
  postForm<T>(path: string, form: FormData, options: RequestOptions = {}): Promise<T> {
    return this.request<T>("POST", path, { ...options, form, body: undefined });
  }
  /** A multipart POST whose NDJSON response is handed to `onLine` line by line; resolves when it ends. */
  async postFormLines(path: string, form: FormData, onLine: (line: unknown) => void,
    options: RequestOptions = {}): Promise<void> {
    await this.request<unknown>("POST", path, { ...options, form, body: undefined, onLine });
  }

  async request<T>(method: ApiMethod, path: string, options: RequestOptions = {}): Promise<T> {
    if (!path.startsWith("/") || path.startsWith("//")) {
      throw new ApiError("validation", null, { message: `Invalid API path: ${path}` });
    }
    this.assertScope();
    const session = await this.auth.currentSession();
    this.assertScope(session?.userId);
    if (!session) {
      throw new ApiError("unauthorized", 401, { message: "Not signed in" });
    }
    const url = this.buildUrl(path, options.query);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
    const external = options.signal;
    const onExternalAbort = () => controller.abort();
    const scopeSignal = this.requestScope?.signal;
    external?.addEventListener("abort", onExternalAbort);
    scopeSignal?.addEventListener("abort", onExternalAbort);
    if (external?.aborted || scopeSignal?.aborted) controller.abort();
    try {
      if (controller.signal.aborted) throw new DOMException("Request aborted", "AbortError");
      const response = await fetch(url, {
        method,
        headers: {
          Accept: "application/json",
          ...(options.body !== undefined && !options.form ? { "Content-Type": "application/json" } : {}),
          Authorization: `Bearer ${session.accessToken}`,
        },
        body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
        signal: controller.signal,
        ...(options.keepalive ? { keepalive: true } : {}),
      });
      if (options.onLine && response.ok && response.body) {
        await readLines(response.body, options.onLine, () => this.assertScope(session.userId));
        return undefined as T;
      }
      const parsed = options.blob && response.ok ? await response.blob() : await this.parseBody(response);
      // A late old-user response (including 401) cannot affect the new session.
      this.assertScope(session.userId);
      if (response.status === 401) {
        this.onUnauthorized?.();
        throw new ApiError("unauthorized", 401, detailFromResponse(parsed));
      }
      if (!response.ok) {
        throw kindFromStatus(response.status, detailFromResponse(parsed));
      }
      if (typeof parsed === "string") {
        throw new ApiError("parse", response.status, { message: "Non-JSON learner API response" });
      }
      return parsed as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (isAbortError(error) && external?.aborted) {
        throw new ApiError("timeout", null, { message: "Request aborted" });
      }
      if (isAbortError(error)) {
        throw new ApiError("timeout", null, { message: "Request timed out" });
      }
      throw new ApiError("network", null, {
        message: "Network request failed",
        raw: String(error),
      });
    } finally {
      clearTimeout(timeout);
      external?.removeEventListener("abort", onExternalAbort);
      scopeSignal?.removeEventListener("abort", onExternalAbort);
    }
  }

  async currentPrincipal(): Promise<string> {
    this.assertScope();
    const session = await this.auth.currentSession();
    this.assertScope(session?.userId);
    if (!session) throw new ApiError("unauthorized", 401, { message: "Not signed in" });
    return session.userId;
  }

  private assertScope(principalId?: string) {
    const scope = this.requestScope;
    if (scope && (scope.signal.aborted || (principalId !== undefined && scope.principalId !== principalId))) {
      throw new ApiError("unauthorized", 401, { message: "Authentication changed" });
    }
  }

  buildUrl(path: string, query?: Record<string, string>): string {
    const normalized = `${this.baseUrl}${path}`;
    if (!query || Object.keys(query).length === 0) return normalized;
    const params = new URLSearchParams(query);
    return `${normalized}?${params.toString()}`;
  }

  private async parseBody(response: Response): Promise<unknown> {
    const text = await response.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      // Non-JSON body: for error responses the status classification matters
      // more than the body; success with non-JSON is rejected by the caller.
      return text;
    }
  }
}

export function kindFromStatus(status: number, detail: ReturnType<typeof detailFromResponse>): ApiError {
  if (status === 401) return new ApiError("unauthorized", 401, detail);
  if (status === 404) return new ApiError("not_found", 404, detail);
  if (status === 409) return new ApiError("conflict", 409, detail);
  if (status === 400 || status === 422) return new ApiError("validation", status, detail);
  if (status >= 500) return new ApiError("server", status, detail);
  return new ApiError("server", status, detail);
}

async function readLines(body: ReadableStream<Uint8Array>, onLine: (line: unknown) => void, check: () => void) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  const emit = (line: string) => {
    if (!line.trim()) return;
    check(); // a late line for a signed-out learner is dropped
    try {
      onLine(JSON.parse(line));
    } catch (error) {
      if (error instanceof ApiError) throw error;
      // A malformed line is skipped; the next one may still be usable.
    }
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffered += decoder.decode(value, { stream: true });
    let cut = buffered.indexOf("\n");
    while (cut >= 0) {
      emit(buffered.slice(0, cut));
      buffered = buffered.slice(cut + 1);
      cut = buffered.indexOf("\n");
    }
  }
  emit(buffered + decoder.decode());
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
