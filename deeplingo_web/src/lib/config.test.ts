import { afterEach, describe, expect, it, vi } from "vitest";
import { isConfigured, isSafeProductionApiOrigin, loadConfig } from "./config";

function env(overrides: Record<string, string> = {}): Record<string, string | undefined> {
  return {
    VITE_API_BASE_URL: "https://api.example.com/api/v1/v3",
    VITE_SUPABASE_URL: "https://project.supabase.co",
    VITE_SUPABASE_PUBLISHABLE_KEY: "publishable-key",
    ...overrides,
  };
}

describe("config loading", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("loads the three browser-safe variables", () => {
    const config = loadConfig(env());
    expect(config).toEqual({
      apiBaseUrl: "https://api.example.com/api/v1/v3",
      supabaseUrl: "https://project.supabase.co",
      supabasePublishableKey: "publishable-key",
    });
  });

  it("ignores non-VITE_ variables entirely", () => {
    const config = loadConfig({
      ...env(),
      SUPABASE_SERVICE_ROLE_KEY: "must-never-load",
      REDIS_URL: "redis://must-never-load",
      AI_API_KEY: "must-never-load",
    });
    expect(JSON.stringify(config)).not.toContain("must-never-load");
  });
});

describe("configuration validation — development/test", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("accepts absolute HTTPS API base URLs", () => {
    expect(isConfigured(loadConfig(env()))).toBe(true);
  });

  it("accepts a same-origin relative API base URL", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "/api/v1/v3" })))).toBe(true);
  });

  it("accepts an http localhost FastAPI base for local development", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "http://localhost:8000/api/v1/v3" })))).toBe(true);
  });

  it("accepts an http localhost Supabase URL for local development", () => {
    expect(isConfigured(loadConfig(env({ VITE_SUPABASE_URL: "http://127.0.0.1:54321" })))).toBe(true);
  });

  it("rejects a relative base outside the learner API prefix", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "/other" })))).toBe(false);
  });

  it("rejects a trailing slash base", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "/api/v1/v3/" })))).toBe(false);
  });

  it("rejects a missing publishable key", () => {
    expect(isConfigured(loadConfig(env({ VITE_SUPABASE_PUBLISHABLE_KEY: "" })))).toBe(false);
  });

  it("rejects empty configuration", () => {
    expect(isConfigured(loadConfig({}))).toBe(false);
  });
});

describe("configuration validation — production", () => {
  it("accepts an absolute HTTPS API origin", () => {
    expect(isConfigured(loadConfig(env()), true)).toBe(true);
  });

  it("accepts a same-origin relative API base", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "/api/v1/v3" })), true)).toBe(true);
  });

  it("rejects plain-HTTP API origins", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "http://api.example.com/api/v1/v3" })), true)).toBe(false);
  });

  it("rejects localhost API origins", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "http://localhost:8000/api/v1/v3" })), true)).toBe(false);
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "https://localhost/api/v1/v3" })), true)).toBe(false);
  });

  it("rejects loopback and private-range API origins", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "https://127.0.0.1/api/v1/v3" })), true)).toBe(false);
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "https://10.1.2.3/api/v1/v3" })), true)).toBe(false);
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "https://192.168.1.10/api/v1/v3" })), true)).toBe(false);
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "https://172.16.5.5/api/v1/v3" })), true)).toBe(false);
  });

  it("rejects development-only hostnames", () => {
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "https://api.dev.local/api/v1/v3" })), true)).toBe(false);
    expect(isConfigured(loadConfig(env({ VITE_API_BASE_URL: "https://api.example.test/api/v1/v3" })), true)).toBe(false);
  });

  it("rejects non-HTTPS Supabase URLs", () => {
    expect(isConfigured(loadConfig(env({ VITE_SUPABASE_URL: "http://project.supabase.co" })), true)).toBe(false);
  });

  it("rejects localhost Supabase URLs", () => {
    expect(isConfigured(loadConfig(env({ VITE_SUPABASE_URL: "http://localhost:54321" })), true)).toBe(false);
  });

  it("still requires the publishable key in production", () => {
    expect(isConfigured(loadConfig(env({ VITE_SUPABASE_PUBLISHABLE_KEY: "" })), true)).toBe(false);
  });
});

describe("isSafeProductionApiOrigin", () => {
  it("accepts https and rejects everything else", () => {
    expect(isSafeProductionApiOrigin("https://api.example.com/api/v1/v3")).toBe(true);
    expect(isSafeProductionApiOrigin("http://api.example.com/api/v1/v3")).toBe(false);
    expect(isSafeProductionApiOrigin("ws://api.example.com")).toBe(false);
    expect(isSafeProductionApiOrigin("https://example.com")).toBe(true);
  });

  it("rejects malformed URLs", () => {
    expect(isSafeProductionApiOrigin("not a url")).toBe(false);
  });
});
