import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { QueryClientProvider, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { AuthActionFailure, type AuthGateway, type AuthSessionSnapshot } from "../lib/auth/authGateway";
import type { RequestScope } from "../lib/api/apiClient";
import { createAppQueryClient } from "./queryClient";
import { clearPendingSubmissions } from "../features/shared/activities/pendingSubmissionStore";
import { T, tr } from "../i18n/i18n";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface LearnerScope extends RequestScope {
  client: QueryClient;
  controller: AbortController;
}
interface AuthState {
  status: AuthStatus;
  scope: LearnerScope | null;
  revision: number;
  error: string | null;
  recoveryObserved: boolean;
}
interface AuthContextValue {
  status: AuthStatus;
  principalId: string | null;
  gateway: AuthGateway;
  requestScope: RequestScope | undefined;
  publicQueryClient: QueryClient;
  signOut: () => Promise<void>;
  recoveryObserved: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function dispose(scope: LearnerScope | null) {
  // Cancels transport and query work; old callbacks retain only a retired cache.
  scope?.controller.abort();
  scope?.client.clear();
}

export function AuthProvider({ gateway, children }: { gateway: AuthGateway; children: ReactNode }) {
  const publicQueryClient = useQueryClient();
  const current = useRef<AuthState>({ status: "loading", scope: null, revision: 0, error: null, recoveryObserved: false });
  const [state, setState] = useState(current.current);
  const logoutPending = useRef(false);
  const logoutPromise = useRef<Promise<void> | null>(null);

  const publish = useCallback((session: AuthSessionSnapshot | null, error: string | null = null) => {
    const previous = current.current;
    const principalId = session?.userId || null; // LOCAL namespace only, never an API input.
    if (previous.scope && previous.scope.principalId !== principalId) {
      // Initial unresolved/null auth is not a logout. Keep A's record
      // quarantined until the verified same principal can restore it.
      void clearPendingSubmissions(previous.scope.principalId).catch(() => {
        // A later pending read validates its principal and fails closed.
      });
    }
    let scope = previous.scope;
    let revision = previous.revision;
    if ((scope?.principalId ?? null) !== principalId || scope?.signal.aborted || previous.status === "loading") {
      dispose(scope);
      scope = null;
      if (principalId) {
        const controller = new AbortController();
        scope = { principalId, controller, signal: controller.signal, client: createAppQueryClient() };
      }
      revision += 1;
    }
    const next: AuthState = { status: principalId ? "authenticated" : "unauthenticated", scope, revision, error, recoveryObserved: previous.recoveryObserved };
    current.current = next;
    setState(next);
  }, []);

  useEffect(() => {
    let active = true;
    let events = 0;
    // Capture bootstrap guards before subscribing: an immediate SDK snapshot wins.
    const initialRevision = current.current.revision;
    const unsubscribe = gateway.onAuthStateChange((session, event) => {
      events += 1;
      if (event === "PASSWORD_RECOVERY") {
        // Ephemeral recovery-context signal: the current navigation entered a
        // Supabase password-recovery flow. This is UI state, not authority.
        current.current.recoveryObserved = true;
        setState(s => ({ ...s, recoveryObserved: true }));
      }
      if (event === "SIGNED_OUT") {
        current.current.recoveryObserved = false;
      }
      // Consume the SDK snapshot synchronously. No nested getSession under its lock.
      if (active && !logoutPending.current && !current.current.error) publish(session);
    });
    gateway.currentSession().then(
      (session) => { if (active && events === 0 && current.current.revision === initialRevision && !logoutPending.current && !current.current.error) publish(session); },
      () => { if (active && events === 0 && current.current.revision === initialRevision && !logoutPending.current) publish(null, tr("Your session could not be restored. Please reload or sign out.")); },
    );
    return () => {
      active = false;
      unsubscribe();
      dispose(current.current.scope);
    };
  }, [gateway, publish]);

  const signOut = useCallback((): Promise<void> => {
    if (logoutPromise.current) return logoutPromise.current;
    logoutPending.current = true;
    const previous = current.current;
    dispose(previous.scope);
    if (previous.scope) {
      void clearPendingSubmissions(previous.scope.principalId).catch(() => {
        // The former principal cannot reach learner UI; a B read is fenced.
      });
    }
    const blocked: AuthState = { status: "loading", scope: null, revision: previous.revision + 1, error: null, recoveryObserved: false };
    current.current = blocked;
    setState(blocked); // Hide old learner UI before waiting on the Auth API.
    const operation = (async () => {
      try {
        await gateway.signOut();
        publish(null);
      } catch {
        const message = tr("Sign out could not be confirmed. Learner data has been cleared. Retry sign out or reload.");
        publish(null, message); // Fail closed; do not silently restore the old learner.
        throw new AuthActionFailure(message);
      } finally {
        logoutPending.current = false;
        logoutPromise.current = null;
      }
    })();
    logoutPromise.current = operation;
    return operation;
  }, [gateway, publish]);

  const value = useMemo<AuthContextValue>(() => ({
    status: state.status,
    principalId: state.scope?.principalId ?? null,
    gateway,
    requestScope: state.scope ?? undefined,
    publicQueryClient,
    signOut,
    recoveryObserved: state.recoveryObserved,
  }), [state, gateway, publicQueryClient, signOut]);

  return <AuthContext.Provider value={value}>
    {state.error ? <div className="page-center">
      <p role="alert">{state.error}</p>
      <button className="dl-btn dl-btn--primary" onClick={() => { void signOut().catch(() => {}); }}><T>Retry sign out</T></button>
    </div> : state.status === "loading" ? <div className="page-center" role="status"><T>Restoring session…</T></div> :
      <QueryClientProvider key={state.revision} client={state.scope?.client ?? publicQueryClient}>
        {children}
      </QueryClientProvider>}
  </AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
