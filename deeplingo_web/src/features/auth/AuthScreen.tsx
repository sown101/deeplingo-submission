import { useState, type FormEvent } from "react";
import { Link, useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { useAuth } from "../../app/AuthProvider";
import { AuthActionFailure } from "../../lib/auth/authGateway";
import { safeInternalLocation } from "../../lib/navigation";
import { AuthLayout } from "./AuthLayout";
import { T, tr } from "../../i18n/i18n";

export function AuthScreen() {
  const { gateway } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const mode = params.get("mode") === "signup" ? "signup" : "signin";
  function setMode(nextMode: "signin" | "signup") {
    const next = new URLSearchParams(params);
    if (nextMode === "signup") next.set("mode", "signup"); else next.delete("mode");
    setParams(next, { replace: true, state: location.state });
  }
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(
    (location.state as { notice?: string } | null)?.notice ?? null,
  );

  // Return locations must remain internal application routes.
  const from = safeInternalLocation((location.state as { from?: unknown } | null)?.from) ?? "/onboarding";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "signup") {
        const result = await gateway.signUp(email.trim(), password);
        if (result.needsConfirmation) {
          setNotice(tr("Check your email to confirm your account, then sign in."));
          setMode("signin");
        } else {
          // New learners pass the server-checked onboarding gate first.
          navigate("/onboarding", { replace: true });
        }
      } else {
        await gateway.signIn(email.trim(), password);
        // /onboarding redirects complete profiles straight to /home.
        navigate(from ?? "/onboarding", { replace: true });
      }
    } catch (err) {
      if (err instanceof AuthActionFailure) {
        setError(err.message);
      } else {
        setError(tr("Authentication failed. Please try again."));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      <form className="auth-card" onSubmit={submit}>
        <h1>{mode === "signin" ? <T>Welcome back</T> : <T>Create your account</T>}</h1>
        <p className="muted">
          {mode === "signin" ? <T>Sign in to continue learning.</T> : <T>Create your learner account.</T>}
        </p>
        <label htmlFor="email"><T>Email</T></label>
        <input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="password"><T>Password</T></label>
        <input
          id="password"
          type="password"
          required
          minLength={8}
          autoComplete={mode === "signin" ? "current-password" : "new-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="notice" role="status">
            {notice}
          </p>
        ) : null}
        <button className="dl-btn dl-btn--primary" type="submit" disabled={busy}>
          {busy ? <T>Please wait…</T> : mode === "signin" ? <T>Sign in</T> : <T>Sign up</T>}
        </button>
        {mode === "signin" ? (
          <Link className="dl-btn dl-btn--plain" to="/forgot-password">
            <T>Forgot password?</T>
          </Link>
        ) : null}
        <button
          type="button"
          className="dl-btn dl-btn--plain"
          onClick={() => {
            setMode(mode === "signin" ? "signup" : "signin");
            setError(null);
            setNotice(null);
          }}
        >
          {mode === "signin" ? <T>Need an account? Sign up</T> : <T>Already have an account? Sign in</T>}
        </button>
        <Link className="dl-btn dl-btn--plain" to="/privacy">
          <T>Privacy</T>
        </Link>
      </form>
    </AuthLayout>
  );
}
