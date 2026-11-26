// WEB-9E — read-only backend capability preflight for the Web Product E2E.
//
// Runs BEFORE any disposable learner or browser session is created and never
// mutates learner or shared state. It classifies the selected API origin and
// development database into exactly one verdict:
//
//   PREFLIGHT_CLASSIFICATION=READY                     health + V3 + Auth + required RPC
//   PREFLIGHT_CLASSIFICATION=BACKEND_RUNTIME_NOT_MIGRATED   required v3 RPC absent
//   PREFLIGHT_CLASSIFICATION=BACKEND_RUNTIME_UNAVAILABLE    origin invalid/unreachable or V3 not mounted
//   PREFLIGHT_CLASSIFICATION=PREFLIGHT_INCONCLUSIVE    detector calibration failed (never guess)
//   PREFLIGHT_CLASSIFICATION=HARNESS_MISCONFIGURED     missing/invalid required configuration
//
// Exit codes: 0 READY, 10 NOT_MIGRATED, 11 UNAVAILABLE, 12 INCONCLUSIVE,
// 2 MISCONFIGURED. A non-zero exit must fail the gate; only 0 proceeds.
//
// Configuration (no defaults, no port guessing, no production fallback):
//   E2E_API_ORIGIN               required absolute http(s) origin, no path
//                                (e.g. http://localhost:8000)
//   E2E_SUPABASE_URL or SUPABASE_URL
//   E2E_SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_ROLE_KEY
//
// RPC existence probe safety: `admit_video_content_work` is called with
// validly shaped arguments whose action value is rejected by the function's
// FIRST statement (validation raises before any read or write), so a present
// function fails closed with zero side effects; an absent function returns
// PostgREST PGRST202. The probe is bracketed by two calibrations so a broken
// detector reports INCONCLUSIVE instead of a false backend verdict.

const MISSING_RPC = "admit_video_content_work";

function classify(code) {
  console.log(`PREFLIGHT_CLASSIFICATION=${code}`);
  if (process.env.GITHUB_ACTIONS === "true" && code !== "READY") {
    console.log(`::error::Web Product E2E preflight classified ${code}`);
  }
  process.exit(
    { READY: 0, BACKEND_RUNTIME_NOT_MIGRATED: 10, BACKEND_RUNTIME_UNAVAILABLE: 11,
      PREFLIGHT_INCONCLUSIVE: 12, HARNESS_MISCONFIGURED: 2 }[code],
  );
}

const note = (step, detail) => console.log(`[preflight] ${step}: ${detail}`);

const TIMEOUT = { signal: AbortSignal.timeout(15_000) };

async function get(url, headers = {}) {
  try {
    return await fetch(url, { ...TIMEOUT, headers });
  } catch (error) {
    return { networkError: String(error?.cause?.code ?? error) };
  }
}

async function post(url, headers, body) {
  try {
    return await fetch(url, {
      ...TIMEOUT,
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
    });
  } catch (error) {
    return { networkError: String(error?.cause?.code ?? error) };
  }
}

// --- configuration ---------------------------------------------------------
const rawOrigin = process.env.E2E_API_ORIGIN;
if (!rawOrigin || !rawOrigin.trim()) {
  console.error("[preflight] E2E_API_ORIGIN is required; refusing to guess an API port");
  classify("HARNESS_MISCONFIGURED");
}
let origin;
try {
  origin = new URL(rawOrigin.trim());
} catch {
  console.error("[preflight] E2E_API_ORIGIN is not a valid URL");
  classify("HARNESS_MISCONFIGURED");
}
if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password
    || !["", "/"].includes(origin.pathname)) {
  console.error("[preflight] E2E_API_ORIGIN must be an absolute http(s) origin without a path or credentials");
  classify("HARNESS_MISCONFIGURED");
}
const supabaseUrl =
  process.env.E2E_SUPABASE_URL?.trim() || process.env.SUPABASE_URL?.trim() || null;
const serviceKey =
  process.env.E2E_SUPABASE_SERVICE_ROLE_KEY?.trim()
  || process.env.SUPABASE_SERVICE_ROLE_KEY?.trim()
  || null;
if (!supabaseUrl || !serviceKey) {
  console.error("[preflight] Supabase URL and service-role key are required (E2E_* or SUPABASE_* names)");
  classify("HARNESS_MISCONFIGURED");
}
const restUrl = supabaseUrl.replace(/\/$/, "");
const restHeaders = { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` };

// --- 1. backend health -----------------------------------------------------
const health = await get(`${origin.origin}/health`);
if (health.networkError) {
  console.error(`[preflight] health unreachable at ${origin.origin}/health (${health.networkError})`);
  classify("BACKEND_RUNTIME_UNAVAILABLE");
}
if (health.status !== 200) {
  console.error(`[preflight] health returned HTTP ${health.status}`);
  classify("BACKEND_RUNTIME_UNAVAILABLE");
}
note("health", "200");

// --- 2. V3 API mounted on that origin -------------------------------------
const openapi = await get(`${origin.origin}/openapi.json`);
if (openapi.networkError || openapi.status !== 200) {
  console.error(`[preflight] FastAPI openapi.json unavailable (status ${openapi.status ?? "network"})`);
  classify("BACKEND_RUNTIME_UNAVAILABLE");
}
let v3Mounted = false;
try {
  const paths = Object.keys((await openapi.json()).paths ?? {});
  v3Mounted = paths.includes("/api/v1/v3/learner/me/library/videos");
} catch {
  v3Mounted = false;
}
if (!v3Mounted) {
  console.error(`[preflight] V3 learner API routes are not mounted on ${origin.origin}`);
  classify("BACKEND_RUNTIME_UNAVAILABLE");
}
note("v3-routes", "/api/v1/v3/learner/me/library/videos mounted");

// --- 3. Supabase Auth reachable -------------------------------------------
const authHealth = await get(`${restUrl}/auth/v1/health`, restHeaders);
if (authHealth.networkError || authHealth.status !== 200) {
  console.error(`[preflight] Supabase Auth health unavailable (status ${authHealth.status ?? "network"})`);
  classify("BACKEND_RUNTIME_UNAVAILABLE");
}
note("supabase-auth", "200");

// --- 4. RPC existence detector (calibrated) -------------------------------
async function rpc(name, body) {
  return post(`${restUrl}/rest/v1/rpc/${name}`, restHeaders, body);
}

// Calibration A: a function that must NOT exist answers 404 PGRST202.
const absent = await rpc("deeplingo_preflight_absent_fn", {});
if (absent.networkError) {
  console.error(`[preflight] RPC probe unreachable (${absent.networkError})`);
  classify("BACKEND_RUNTIME_UNAVAILABLE");
}
if (!(absent.status === 404 && (await absent.text()).includes("PGRST202"))) {
  console.error(`[preflight] calibration A failed: absent function answered HTTP ${absent.status}`);
  classify("PREFLIGHT_INCONCLUSIVE");
}

// Calibration B: a function known to exist (granted to service_role, listed
// in PostgREST OpenAPI) answers non-404. p_limit=0 keeps the read-only
// dictionary search row-free.
const present = await rpc("find_word_in_videos", {
  p_word: "preflight-probe",
  p_language: "en",
  p_limit: 0,
});
if (present.networkError) {
  console.error(`[preflight] RPC probe unreachable (${present.networkError})`);
  classify("BACKEND_RUNTIME_UNAVAILABLE");
}
if (present.status === 404) {
  console.error("[preflight] calibration B failed: known-present function answered 404");
  classify("PREFLIGHT_INCONCLUSIVE");
}
note("rpc-detector", "calibrated (absent=404 PGRST202, present=non-404)");

// Probe: a present admit_video_content_work rejects the probe action in its
// first statement (errcode 22023) before touching any row; an absent one
// answers 404 PGRST202 — exactly the PGRST202 the backend observed live.
const admit = await rpc(MISSING_RPC, {
  p_user_id: "00000000-0000-0000-0000-000000000000",
  p_video_id: "00000000-0000-0000-0000-000000000000",
  p_action: "__preflight_probe__",
  p_library_item_id: "00000000-0000-0000-0000-000000000000",
});
if (admit.networkError) {
  console.error(`[preflight] RPC probe unreachable (${admit.networkError})`);
  classify("BACKEND_RUNTIME_UNAVAILABLE");
}
if (admit.status === 404 && (await admit.text()).includes("PGRST202")) {
  console.error(`[preflight] ${MISSING_RPC} is absent from the PostgREST schema cache`);
  console.error("[preflight] backend owner must apply the durable content work intents migration; harness does not touch the database");
  classify("BACKEND_RUNTIME_NOT_MIGRATED");
}
note("admit-rpc", `present (HTTP ${admit.status}; function rejects probe arguments)`);

classify("READY");
