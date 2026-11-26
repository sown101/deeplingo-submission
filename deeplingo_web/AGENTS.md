# React web

Inherits the root [rules](../AGENTS.md). Former web rules are archived in
`../docs/archive/legacy-rules/web-AGENTS.md` (evidence, not authority).

## Commands

Run from `deeplingo_web/`. Scripts are in `package.json`.

- Type check: `npm run typecheck`.
- Unit tests: `npm test`.
- Build: `npm run build`.
- Lint: `npm run lint`.
- Build audit and bundle budget: `npm run audit:build`, `npm run check:bundle`.
- Deterministic browser tests (mocked, no live services): `npm run test:e2e:deterministic`.
- Responsive screenshots (mocked; Chromium, WebKit, Firefox; every screen at 10 viewport sizes; not part of CI): `npm run test:e2e:responsive`, then `npm run report:responsive` (gallery in `test-results/responsive/index.html`). Needs `npx playwright install webkit firefox` once.

## Cautions

- Browser config may hold only the Supabase publishable (anon) key. No service-role, AI,
  database or broker secrets in `VITE_` values.
- Mocked browser tests do not prove live behavior; say which one ran.
