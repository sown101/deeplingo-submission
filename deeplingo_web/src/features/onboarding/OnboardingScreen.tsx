import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { useAuth } from "../../app/AuthProvider";
import type { Language } from "../../lib/api/dto";
import { AuthLayout } from "../auth/AuthLayout";
import { DECLARED_LEVELS } from "../words/wordsModels";
import { T, useT, tr } from "../../i18n/i18n";

export function OnboardingScreen() {
  const t = useT();
  const { onboarding } = useContainer();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { publicQueryClient } = useAuth();
  const profileQuery = useQuery({
    queryKey: ["language-profile"],
    queryFn: () => onboarding.loadProfile(),
    retry: false,
  });
  const languagesQuery = useQuery({
    queryKey: ["languages"],
    queryFn: () => onboarding.loadLanguages(),
    retry: false,
  }, publicQueryClient);

  const [learning, setLearning] = useState<string>("");
  const [support, setSupport] = useState<string>("");
  const [level, setLevel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (profileQuery.data?.is_complete) {
      navigate("/home", { replace: true });
    }
  }, [profileQuery.data, navigate]);

  const languages: Language[] = (languagesQuery.data ?? []).filter((l) => l.is_active);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const profile = await onboarding.saveProfile({
        learningLanguageCode: learning,
        supportLanguageCode: support,
        ...(level ? { declaredLevel: level } : {}),
      });
      queryClient.setQueryData(["language-profile"], profile);
      navigate("/home", { replace: true });
    } catch {
      setError(tr("We could not save your language choice. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  if (profileQuery.isLoading || languagesQuery.isLoading) {
    return (
      <div className="page-center" role="status">
        <p><T>Loading your profile…</T></p>
      </div>
    );
  }
  if (profileQuery.isError || languagesQuery.isError) {
    return (
      <div className="page-center">
        <p><T>We could not load your learner profile.</T></p>
        <button className="dl-btn dl-btn--primary" onClick={() => { profileQuery.refetch(); languagesQuery.refetch(); }}>
          <T>Retry</T>
        </button>
      </div>
    );
  }

  return (
    <AuthLayout wide>
      <form className="auth-card" onSubmit={submit}>
        <p className="eyebrow"><T>Set up · 1 minute</T></p>
        <h1><T>Choose your languages</T></h1>
        <p className="muted"><T>What do you want to learn, and in which language?</T></p>
        <LanguageChoice
          name="learning"
          legend="Learning language"
          languages={languages}
          value={learning}
          onChange={code => { setLearning(code); setLevel(""); }}
        />
        <LanguageChoice
          name="support"
          legend="Support language"
          languages={languages}
          value={support}
          onChange={setSupport}
        />
        {(DECLARED_LEVELS[learning]?.length ?? 0) > 0 ? <div className="stack tight">
          <label htmlFor="onboarding-level"><T>My level (optional)</T></label>
          <select id="onboarding-level" value={level} onChange={event => setLevel(event.target.value)}>
            <option value="">{t("Skip for now")}</option>
            {DECLARED_LEVELS[learning].map(value => <option key={value} value={value}>{value}</option>)}
          </select>
          <span className="muted small"><T>Your own estimate, not a test score. You can change it in Profile.</T></span>
        </div> : null}
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        <button className="dl-btn dl-btn--primary" type="submit" disabled={busy || learning === support}>
          {busy ? <T>Saving…</T> : <T>Start learning</T>}
        </button>
      </form>
    </AuthLayout>
  );
}

function LanguageChoice({
  name,
  legend,
  languages,
  value,
  onChange,
}: {
  name: string;
  legend: string;
  languages: { code: string; name_en: string }[];
  value: string;
  onChange: (code: string) => void;
}) {
  const t = useT();
  return (
    <fieldset className="choice-group">
      <legend>{t(legend)}</legend>
      <div className="choice-grid">
        {languages.map((l) => (
          <label key={l.code} className={value === l.code ? "choice-card selected" : "choice-card"}>
            <input
              type="radio"
              name={name}
              value={l.code}
              required
              checked={value === l.code}
              onChange={() => onChange(l.code)}
            />
            <span className="choice-badge" aria-hidden="true">
              {l.code.slice(0, 2).toUpperCase()}
            </span>
            <span className="choice-label">{t(l.name_en)}</span>
            <span className="choice-tick" aria-hidden="true" />
          </label>
        ))}
      </div>
    </fieldset>
  );
}
