// Build-time configuration. Never ship a service-role key in a client build.
//
// Environment separation:
//   - development/test (vite dev): absolute http(s) and localhost API bases
//     are allowed so the Vite proxy / local FastAPI workflow keeps working.
//   - production (vite build): same-origin relative API bases remain valid;
//     absolute API origins must be HTTPS and must not point at localhost,
//     loopback, link-local, private-range hosts, or *.local dev names.

export interface AppConfig {
  apiBaseUrl: string;
  supabaseUrl: string;
  supabasePublishableKey: string;
}

export function loadConfig(env: Record<string, string | undefined> = import.meta.env): AppConfig {
  const apiBaseUrl = (env.VITE_API_BASE_URL ?? "").trim();
  const supabaseUrl = (env.VITE_SUPABASE_URL ?? "").trim();
  const supabasePublishableKey = (env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "").trim();
  return { apiBaseUrl, supabaseUrl, supabasePublishableKey };
}

export function isConfigured(config: AppConfig, isProduction = false): boolean {
  if (!config.supabasePublishableKey) return false;
  if (!isProduction && !isHttpsUrl(config.supabaseUrl) && !isLocalHttpUrl(config.supabaseUrl)) {
    return false;
  }
  if (isProduction && !isHttpsUrl(config.supabaseUrl)) return false;
  const api = config.apiBaseUrl;
  if (!api || api.endsWith("/")) return false;
  // Same-origin deployments may use a relative API base ("/api/v1/v3");
  // cross-origin deployments must be absolute URLs.
  if (api.startsWith("/")) return api.includes("/api/v1/v3");
  if (!api.startsWith("https://") && !api.startsWith("http://")) return false;
  if (!api.includes("/api/v1/v3")) return false;
  if (isProduction) return isSafeProductionApiOrigin(api);
  return true;
}

// Rejects insecure or development-only API origins in production builds.
// No internal values from the URL are surfaced to users.
export function isSafeProductionApiOrigin(absoluteUrl: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(absoluteUrl);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase();
  if (host === "localhost" || host === "127.0.0.1" || host === "::1" || host === "[::1]") return false;
  if (host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".test") || host.endsWith(".invalid")) return false;
  if (isPrivateIpv4(host)) return false;
  return true;
}

function isPrivateIpv4(host: string): boolean {
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!match) return false;
  const octets = match.slice(1).map(Number);
  if (octets.some((o) => o > 255)) return false;
  const [a, b] = octets;
  if (a === 10 || a === 127 || a === 0) return true;
  if (a === 192 && b === 168) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 169 && b === 254) return true;
  return false;
}

function isHttpsUrl(value: string): boolean {
  if (!value) return false;
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

function isLocalHttpUrl(value: string): boolean {
  if (!value) return false;
  try {
    const parsed = new URL(value);
    return (
      parsed.protocol === "http:" &&
      (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1")
    );
  } catch {
    return false;
  }
}
