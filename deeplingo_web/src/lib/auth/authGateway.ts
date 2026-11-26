import { GoTrueClient } from "@supabase/auth-js";
import type { AppConfig } from "../config";

// The Web client uses ONLY Supabase Auth. The full supabase-js monolith
// (storage/postgrest/realtime/functions) is not needed by any browser code
// path, so the auth client is used directly (identical implementation,
// session format, and storage key derivation that supabase-js delegates to).
// FastAPI remains the only learner API; this client talks solely to
// Supabase Auth endpoints.

export interface AuthSessionSnapshot {
  userId: string;
  accessToken: string;
}

export interface AuthGateway {
  getClient(): GoTrueClient;
  currentSession(): Promise<AuthSessionSnapshot | null>;
  onAuthStateChange(callback: (session: AuthSessionSnapshot | null, event: string) => void): () => void;
  signUp(email: string, password: string): Promise<{ needsConfirmation: boolean }>;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  resetPassword(email: string, redirectTo: string): Promise<void>;
  updatePassword(password: string): Promise<void>;
}

function projectRef(supabaseUrl: string): string {
  try {
    return new URL(supabaseUrl).hostname.split(".")[0];
  } catch {
    return "app";
  }
}

export function createSupabaseGateway(config: AppConfig): AuthGateway {
  // Mirrors the client supabase-js would construct for auth:
  // storageKey "sb-<project-ref>-auth-token", persisted session,
  // auto refresh, and redirect-session detection.
  const client = new GoTrueClient({
    url: `${config.supabaseUrl.replace(/\/+$/, "")}/auth/v1`,
    headers: {
      apikey: config.supabasePublishableKey,
      Authorization: `Bearer ${config.supabasePublishableKey}`,
    },
    storageKey: `sb-${projectRef(config.supabaseUrl)}-auth-token`,
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  });

  return {
    getClient: () => client,
    currentSession: async () => {
      const { data, error } = await client.getSession();
      if (error) throw new AuthActionFailure("Session could not be restored.");
      const session = data.session;
      if (!session || !session.access_token) return null;
      return { userId: session.user.id, accessToken: session.access_token };
    },
    onAuthStateChange: (callback) => {
      const { data } = client.onAuthStateChange((event, session) => callback(
        session?.access_token ? { userId: session.user.id, accessToken: session.access_token } : null,
        event,
      ));
      return () => data.subscription.unsubscribe();
    },
    signUp: async (email, password) => {
      const { data, error } = await client.signUp({ email, password });
      if (error) throw new AuthActionFailure(error.message);
      return { needsConfirmation: !data.session };
    },
    signIn: async (email, password) => {
      const { error } = await client.signInWithPassword({ email, password });
      if (error) throw new AuthActionFailure(error.message);
    },
    signOut: async () => {
      const { error } = await client.signOut();
      if (error) throw new AuthActionFailure("Sign out could not be confirmed.");
    },
    resetPassword: async (email, redirectTo) => {
      const { error } = await client.resetPasswordForEmail(email, { redirectTo });
      if (error) throw new AuthActionFailure(error.message);
    },
    updatePassword: async (password) => {
      const { error } = await client.updateUser({ password });
      if (error) throw new AuthActionFailure(error.message);
    },
  };
}

export class AuthActionFailure extends Error {}
