# Web Production Boundary — Deployment & Security Policy

Status: WEB-8B. Deployment/infrastructure documentation. No product behavior
is defined here.

## 1. Deployment model

Current development deployment (2026-10-11): **cross-origin**. The SPA is on
Firebase Hosting (`firebase.json`: SPA rewrite, `no-cache` shell, immutable hashed
assets) and calls the API on a GCP VM behind Caddy HTTPS; `BACKEND_CORS_ORIGINS`
lists the Hosting origins. See the [GCP runbook](../../docs/runbooks/gcp-staging.md).
Both architectures below remain supported by configuration; nothing in the app
assumes either one.

| Model | Browser API base | CORS | Notes |
| --- | --- | --- | --- |
| **Same-origin** (web + API behind one host, e.g. reverse proxy `/api/*`) | `/api/v1/v3` (relative) | CORS irrelevant (no cross-origin browser request) | Preferred: smallest browser boundary |
| **Cross-origin** (`app.example.com` → `api.example.com`) | `https://api.example.com/api/v1/v3` | Backend `BACKEND_CORS_ORIGINS=https://app.example.com` | Explicit origin allow-list required |

## 2. Production API-origin policy (enforced in code)

`src/lib/config.ts` distinguishes builds:

- **Development/test** (`vite dev`): relative `/api/v1/v3`, `http://localhost`
  and `http://127.0.0.1` API/Supabase URLs remain allowed — the local
  FastAPI + Vite-proxy workflow is unchanged.
- **Production** (`vite build`, `import.meta.env.PROD`):
  - same-origin relative base (`/api/v1/v3`) stays valid;
  - absolute API origins must be **https** and must NOT point at
    `localhost`, `127.0.0.1`, `::1`, `*.localhost`, `*.local`, `*.test`,
    `*.invalid`, link-local (`169.254/16`), or private ranges
    (`10/8`, `127/8`, `172.16/12`, `192.168/16`, `0/8`);
  - non-HTTPS Supabase URLs are rejected.
- Invalid production configuration surfaces a visible configuration screen
  naming the offending variable — the app refuses to boot misconfigured.

## 3. CORS (backend, configuration-driven)

`backend/app/main.py` now derives CORS from `BACKEND_CORS_ORIGINS`
(comma-separated; `backend/app/platform/config.py`):

- explicit configured origins are the production policy — no reflected
  origins, no wildcard default;
- unset → narrow development default (`http://localhost:5173`,
  `http://127.0.0.1:5173`) so local Web development keeps working;
- `allow_credentials=False` — authentication is `Authorization: Bearer`
  (Supabase JWT → FastAPI `CurrentUser`); no cookie auth exists or is
  introduced;
- methods limited to `GET, POST, PUT, OPTIONS`; headers limited to
  `Accept, Content-Type, Authorization`.

Focused tests: `backend/tests/platform/test_cors.py` (configured origin accepted,
unconfigured rejected, dev default works, Authorization preflight allowed,
no wildcard regression, multi-origin configuration).

Same-origin deployments do not require any CORS change — the default dev
allow-list is harmless there because the browser never makes a cross-origin
request.

## 4. Security headers — deployment layer owns them

HTTP response headers cannot be set by React. Until a hosting layer is
selected, the following are the **required** deployment configuration (reverse
proxy / host settings). Every value below is compatible with the actual
client implementation (Supabase Auth fetches, FastAPI API calls, YouTube
`youtube-nocookie.com` iframe + `enablejsapi` postMessage, backend
thumbnails on `i.ytimg.com`).

```text
Content-Security-Policy:
  default-src 'self';
  script-src 'self';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https://i.ytimg.com https://*.ytimg.com;
  connect-src 'self' https://*.supabase.co wss://*.supabase.co https://<api-origin>;
  frame-src https://www.youtube-nocookie.com https://www.youtube.com;
  frame-ancestors 'none';
  base-uri 'self';
  object-src 'none';
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

Per-directive rationale:

- `style-src 'unsafe-inline'` — required ONLY for React inline **style
  attributes** (e.g. dynamic progress-bar widths). No inline `<style>` or
  inline scripts exist in the Vite build. If this is unacceptable, refactor
  the two dynamic-width renderings to CSS custom properties
  (`style-src-attr 'unsafe-hashes'`) — deliberate follow-up, not a casual
  exception.
- `frame-src youtube-nocookie.com` — the Watch player and DICTATION audio
  embed. Distinct from `frame-ancestors`.
- `frame-ancestors 'none'` — DeepLingo itself must not be framed
  (clickjacking). This does NOT restrict DeepLingo from framing YouTube.
- `connect-src` — `'self'` (same-origin API), Supabase Auth/network, and the
  configured API origin for cross-origin deployments. Substitute the real
  `<api-origin>` at deployment time.
- No `wss`/WebSocket is used by current code beyond Supabase Auth keep-alive;
  retained so auth does not break. Revisit if Supabase Auth over HTTPS-only
  polling is confirmed.

If a chosen platform cannot set response headers, that is a deployment
blocker — do not fall back to a meta-policy CSP (`frame-ancestors` is
header-only).

## 5. Source maps

`vite build` ships `sourcemap: false` (explicit). No private observability
vendor exists to receive uploaded maps; publishing maps would expose
application source. Revisit only when an observability pipeline exists.

## 6. Error exposure

- All API failures decode to typed `ApiError` kinds with learner-safe
  messages; no screen renders `error.detail.raw`, stack traces, provider
  payloads, or server configuration (audited; no `console.*` of error
  payloads exists in `src`).
- An application-level `ErrorBoundary` maps unexpected render failures to a
  safe reload state; raw diagnostics are logged only in development
  (`import.meta.env.DEV`).
- Backend 4xx/5xx bodies reach the client as `detail.code`/`detail.message`
  learner-safe projections; unexpected server faults map to retryable safe
  states.

## 7. Secret audit

- Client source references only `VITE_API_BASE_URL`,
  `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` — browser-public by
  design.
- `loadConfig` reads only `VITE_*` variables (unit-tested to ignore
  `SUPABASE_SERVICE_ROLE_KEY`, `REDIS_URL`, `AI_API_KEY`).
- Service-role credentials appear only in server-side processes (FastAPI,
  guarded disposable-learner helper).
- Production bundle audit: run `npm run build`, then search `dist/` for
  `SERVICE_ROLE`, `service_role`, `AI_API_KEY`, `redis`, `postgres`,
  `localhost`, `.env` — the only expected hits are the browser-public
  `VITE_*` values themselves and third-party library names. Results are
  recorded per release in the release checklist.

## 8. Auth / redirect / URL boundary

- Learner identity remains the verified Supabase JWT attached as
  `Authorization: Bearer`; no caller-controlled `user_id` anywhere.
- `src/lib/navigation.ts` restricts sign-in/onboarding return locations to
  internal paths — rejects absolute URLs, scheme-relative (`//host`), the
  `/\host` normalization trick, `javascript:`/`data:` payloads, control
  characters, and oversized values (unit-tested).
- `ApiClient` rejects non-relative API paths (`//evil.example`,
  `https://evil.example`, `https://…`) independent of base configuration
  (unit-tested).

## 9. YouTube boundary

- Playback and dictation embed only backend-provided `external_video_id`
  values validated against `^[A-Za-z0-9_-]{11}$` before any URL is
  constructed (`parsePlayableVideo`, `parseAudioPayload`); no user/backend
  string becomes an arbitrary iframe `src` (deterministic browser spec
  asserts the exact trusted embed origin + id).
- Cue-not-autoplay behavior unchanged (`playsinline`, no `autoplay` param;
  learner-triggered play in DICTATION).
