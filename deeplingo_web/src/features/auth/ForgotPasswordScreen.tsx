import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../app/AuthProvider";
import { AuthActionFailure } from "../../lib/auth/authGateway";
import { AuthLayout } from "./AuthLayout";
import { T, tr } from "../../i18n/i18n";

// Requests a Supabase Auth password-reset email. The UI never reveals
// whether an account exists (neutral confirmation copy).
export function ForgotPasswordScreen() {
  const { gateway } = useAuth();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const redirectTo = window.location.origin + "/reset-password";
      await gateway.resetPassword(email.trim(), redirectTo);
      setSubmitted(true);
    } catch (err) {
      if (err instanceof AuthActionFailure) {
        setError(err.message);
      } else {
        setError(tr("Could not send the reset email. Please try again."));
      }
    } finally {
      setBusy(false);
    }
  }

  if (submitted) {
    return (
      <AuthLayout>
        <form className="auth-card" onSubmit={(e) => e.preventDefault()}>
          <h1><T>Check your email</T></h1>
          <p className="notice" role="status">
            <T>If an account exists for this email, a reset link has been sent.</T>
          </p>
          <button type="button" className="dl-btn dl-btn--plain" onClick={() => setSubmitted(false)}>
            <T>Use a different email</T>
          </button>
          <Link className="dl-btn dl-btn--secondary" to="/signin">
            <T>Back to Sign in</T>
          </Link>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <form className="auth-card" onSubmit={submit}>
        <h1><T>Reset password</T></h1>
        <p className="muted"><T>Enter your email to receive a password-reset link.</T></p>
        <label htmlFor="reset-email"><T>Email</T></label>
        <input
          id="reset-email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        <button className="dl-btn dl-btn--primary" type="submit" disabled={busy}>
          {busy ? <T>Sending…</T> : <T>Send reset link</T>}
        </button>
        <Link className="dl-btn dl-btn--plain" to="/signin">
          <T>Back to Sign in</T>
        </Link>
      </form>
    </AuthLayout>
  );
}
