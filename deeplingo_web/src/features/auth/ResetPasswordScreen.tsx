import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../app/AuthProvider";
import { AuthActionFailure } from "../../lib/auth/authGateway";
import { AuthLayout } from "./AuthLayout";
import { T, tr } from "../../i18n/i18n";

type Phase = "ready" | "submitting" | "invalid";

// The reset-password form is available ONLY when a Supabase PASSWORD_RECOVERY
// event has been observed during the current auth lifecycle. This signal is
// ephemeral UI state derived from the auth event — it is not authority and
// never persists. A normally signed-in user navigating to /reset-password
// without a recovery event sees "invalid link" instead of the form.
export function ResetPasswordScreen() {
  const { status, recoveryObserved, gateway, signOut } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The recovery context is valid when:
  // 1. The PASSWORD_RECOVERY auth event was observed (recoveryObserved)
  // 2. The auth status is authenticated (a recovery session exists)
  // A normally signed-in user without a recovery event sees "invalid link".
  const recoveryValid = recoveryObserved && status === "authenticated";

  const phase: Phase = status === "loading"
    ? "submitting"
    : recoveryValid
      ? "ready"
      : "invalid";

  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError(tr("Passwords do not match."));
      return;
    }
    if (password.length < 6) {
      setError(tr("Password must be at least 6 characters."));
      return;
    }
    setBusy(true);
    gateway
      .updatePassword(password)
      .then(() => signOut())
      .then(() => {
        navigate("/signin", {
          replace: true,
          state: { notice: tr("Password updated. Sign in with your new password.") },
        });
      })
      .catch((err) => {
        if (err instanceof AuthActionFailure) {
          setError(err.message);
        } else {
          setError(tr("Could not update the password. Please try again."));
        }
      })
      .finally(() => setBusy(false));
  }

  if (phase === "invalid") {
    return (
      <AuthLayout>
        <form className="auth-card" onSubmit={(e) => e.preventDefault()}>
          <h1><T>Invalid link</T></h1>
          <p className="error" role="alert">
            <T>This password-reset link is invalid or has expired. Please request a new one.</T>
          </p>
          <Link to="/forgot-password" className="dl-btn dl-btn--secondary">
            <T>Request new link</T>
          </Link>
          <Link to="/signin" className="dl-btn dl-btn--plain">
            <T>Back to Sign in</T>
          </Link>
        </form>
      </AuthLayout>
    );
  }

  // phase === "submitting" (auth settling) or "ready": show the form
  return (
    <AuthLayout>
      <form className="auth-card" onSubmit={submit}>
        <h1><T>Set new password</T></h1>
        <p className="muted"><T>Choose a new password for your account.</T></p>
        <label htmlFor="new-password"><T>New password</T></label>
        <input
          id="new-password"
          type="password"
          required
          minLength={6}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <label htmlFor="confirm-password"><T>Confirm new password</T></label>
        <input
          id="confirm-password"
          type="password"
          required
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          onBlur={() => {
            if (password && confirm && password !== confirm) {
              setError(tr("Passwords do not match."));
            } else {
              setError(null);
            }
          }}
        />
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        <button className="dl-btn dl-btn--primary" type="submit" disabled={busy || !password || !confirm}>
          {busy ? <T>Updating…</T> : <T>Update password</T>}
        </button>
      </form>
    </AuthLayout>
  );
}
