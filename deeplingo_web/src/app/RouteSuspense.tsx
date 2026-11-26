import { Suspense, type ReactNode } from "react";
import { T } from "../i18n/i18n";

// Loading state for lazy-loaded route chunks. Never fabricates learner
// state; route guards (RequireAuth / RequireOnboarding) resolve before the
// lazy route content mounts.
export function RouteLoading() {
  return (
    <div className="page-center" role="status">
      <p><T>Loading…</T></p>
    </div>
  );
}

// In-shell variant: keeps the app shell visible while a screen chunk loads.
export function RouteContentLoading() {
  return (
    <div className="route-loading" role="status">
      <span className="route-loading-bar" aria-hidden="true" />
      <span className="sr-only"><T>Loading…</T></span>
    </div>
  );
}

export function RouteSuspense({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RouteLoading />}>{children}</Suspense>;
}
