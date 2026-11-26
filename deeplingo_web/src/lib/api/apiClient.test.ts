import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./apiClient";
import { ApiError } from "./errors";
import type { AuthGateway } from "../auth/authGateway";

const TOKEN = "test.jwt.token";

function fakeGateway(session: { userId: string; accessToken: string } | null): AuthGateway {
  return {
    getClient: () => {
      throw new Error("not used");
    },
    currentSession: vi.fn().mockResolvedValue(session),
    onAuthStateChange: () => () => {},
    signUp: async () => ({ needsConfirmation: false }),
    signIn: async () => {},
    signOut: async () => {},
    resetPassword: async () => {},
    updatePassword: async () => {},
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ApiClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("attaches Supabase JWT bearer to FastAPI requests", async () => {
    let captured: Headers | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        captured = new Headers(init.headers);
        return jsonResponse(200, { ok: true });
      }),
    );
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }) });
    await client.get("/learner/me/words");
    expect(captured!.get("Authorization")).toBe(`Bearer ${TOKEN}`);
  });

  it("builds URLs with query parameters", () => {
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: fakeGateway(null) });
    expect(client.buildUrl("/learner/me/words", { limit: "1" })).toBe(
      "/api/v1/v3/learner/me/words?limit=1",
    );
  });

  it("throws unauthorized without a session before any network call", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: fakeGateway(null) });
    await expect(client.get("/learner/me/words")).rejects.toMatchObject({ kind: "unauthorized" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps 401 to unauthorized and invokes onUnauthorized once", async () => {
    const onUnauthorized = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, { detail: "Authentication required" })));
    const client = new ApiClient({
      baseUrl: "/api/v1/v3",
      authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }),
      onUnauthorized,
    });
    const error = await client.get("/learner/me/words").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("unauthorized");
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("maps 404/409/422/5xx to typed errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string) => jsonResponse(404, { detail: { code: "library_not_found", message: "missing" } })),
    );
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }) });
    const error = (await client.get("/learner/me/library/videos/x").catch((e) => e)) as ApiError;
    expect(error.kind).toBe("not_found");
    expect(error.detail.code).toBe("library_not_found");

    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string) => jsonResponse(409, { detail: { code: "learning_not_ready" } })),
    );
    const conflict = (await client.get("/x").catch((e) => e)) as ApiError;
    expect(conflict.kind).toBe("conflict");

    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 503 })));
    const server = (await client.get("/x").catch((e) => e)) as ApiError;
    expect(server.kind).toBe("server");
  });

  it("maps network failures without classifying them as ambiguous server answers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }) });
    const error = (await client.get("/x").catch((e) => e)) as ApiError;
    expect(error.kind).toBe("network");
  });

  it("never sends caller-controlled user_id authority fields", async () => {
    let capturedBody: string | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        capturedBody = init.body as string;
        return jsonResponse(202, { command_status: "accepted", item: {} });
      }),
    );
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }) });
    await client.post("/learner/me/library/videos", { url: "https://youtu.be/jNQXAC9IVRw" });
    expect(capturedBody).toBe(JSON.stringify({ url: "https://youtu.be/jNQXAC9IVRw" }));
    expect(capturedBody).not.toContain("user_id");
  });

  it("returns binary bodies as a Blob and keeps typed errors for them", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Uint8Array([1, 2, 3]), { status: 200, headers: { "Content-Type": "audio/mpeg" } })));
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }) });
    const blob = await client.get<Blob>("/learner/me/dictionary/audio", { blob: true });
    expect(blob.size).toBe(3);
    expect(blob.type).toBe("audio/mpeg");

    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(404, { detail: { code: "word_not_found" } })));
    const error = (await client.get("/learner/me/dictionary/audio", { blob: true }).catch((e) => e)) as ApiError;
    expect(error.kind).toBe("not_found");
    expect(error.detail.code).toBe("word_not_found");
  });

  it("rejects non-relative paths", async () => {
    const client = new ApiClient({ baseUrl: "/api/v1/v3", authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }) });
    await expect(client.get("https://evil.example.com/x")).rejects.toMatchObject({ kind: "validation" });
    await expect(client.get("//evil.example.com/x")).rejects.toMatchObject({ kind: "validation" });
  });
});

describe("W01 request lifecycle fencing", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("never serializes the local principal namespace into existing commands", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, {ok:true}));
    vi.stubGlobal("fetch", fetchMock);
    const scope = new AbortController();
    const client = new ApiClient({baseUrl:"/api/v1/v3",authGateway:fakeGateway({userId:"A",accessToken:TOKEN}),requestScope:{principalId:"A",signal:scope.signal}});
    await client.post("/learner/me/session-activities/server-id/answer",{raw_response:{text:"learner input"}});
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/v3/learner/me/session-activities/server-id/answer");
    expect(JSON.parse(init.body as string)).toEqual({raw_response:{text:"learner input"}});
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer " + TOKEN);
  });

  it("a retired A adapter cannot send a follow-up under B's token", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch",fetchMock);
    const controller = new AbortController();
    const client = new ApiClient({baseUrl:"/api/v1/v3",authGateway:fakeGateway({userId:"B",accessToken:"B-token"}),requestScope:{principalId:"A",signal:controller.signal}});
    await expect(client.post("/learner/me/session-activities/A-activity/answer")).rejects.toMatchObject({kind:"unauthorized"});
    controller.abort();
    await expect(client.get("/learner/me/words")).rejects.toMatchObject({kind:"unauthorized"});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("aborts in-flight transport and ignores a late A 401 rather than logging B out", async () => {
    let resolve!: (value: Response) => void;
    let signal: AbortSignal | null = null;
    const pending = new Promise<Response>((yes) => { resolve = yes; });
    const fetchMock = vi.fn((_url: string, init: RequestInit) => { signal = init.signal as AbortSignal; return pending; });
    vi.stubGlobal("fetch",fetchMock);
    const onUnauthorized = vi.fn();
    const controller = new AbortController();
    const client = new ApiClient({baseUrl:"/api/v1/v3",authGateway:fakeGateway({userId:"A",accessToken:TOKEN}),onUnauthorized,requestScope:{principalId:"A",signal:controller.signal}});
    const request = client.get("/learner/me/words").catch((error) => error);
    await Promise.resolve();
    controller.abort();
    expect(signal!.aborted).toBe(true);
    resolve(jsonResponse(401,{detail:"late-A"}));
    expect(await request).toMatchObject({kind:"unauthorized"});
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("rejects a pre-aborted request even when no transport was started", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch",fetchMock);
    const client = new ApiClient({baseUrl:"/api/v1/v3",authGateway:fakeGateway({userId:"A",accessToken:TOKEN}),requestScope:{principalId:"A",signal:controller.signal}});
    await expect(client.get("/learner/me/library/videos")).rejects.toMatchObject({kind:"unauthorized"});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("hands an NDJSON response over line by line, even when a line arrives in pieces", async () => {
    const encoder = new TextEncoder();
    const chunks = ['{"type":"turn","n":1}', String.fromCharCode(10) + '{"type":"au', 'dio"}' + String.fromCharCode(10),
      "not json" + String.fromCharCode(10), '{"type":"done"}'];
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    const client = new ApiClient({ baseUrl: "https://api.example.com", authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }) });
    const lines: unknown[] = [];
    await client.postFormLines("/stream", new FormData(), (line) => lines.push(line));
    expect(lines).toEqual([{ type: "turn", n: 1 }, { type: "audio" }, { type: "done" }]);
  });

  it("an NDJSON request that fails is an ordinary error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(409, { detail: { code: "gone", message: "Gone" } })));
    const client = new ApiClient({ baseUrl: "https://api.example.com", authGateway: fakeGateway({ userId: "u", accessToken: TOKEN }) });
    await expect(client.postFormLines("/stream", new FormData(), vi.fn())).rejects.toBeInstanceOf(ApiError);
  });
});
