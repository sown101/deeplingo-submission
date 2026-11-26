import { Link, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { useAuth } from "../../app/AuthProvider";
import type { Language, LearnerLanguageProfile } from "../../lib/api/dto";
import { SignalsRow, VoiceBox } from "./AgentPrivacyCard";
import { AgentMemoryRow } from "./AgentMemoryCard";
import { TranscriptBox, TranscriptsRow } from "./TranscriptsCard";
import { AppearanceCard } from "./AppearanceCard";
import { DeleteAccountRow } from "./DeleteAccountCard";
import { YourDataCard } from "../privacy/YourDataCard";
import { DECLARED_LEVELS } from "../words/wordsModels";
import { T, useT } from "../../i18n/i18n";
import { Mascot } from "../../design/Mascot";
import "./account.css";

// The learner's page, laid out like the reference: who they are and their numbers on the left,
// settings grouped on the right. Every consent keeps its own switch and its full explanation.
export function AccountScreen() {
  const t = useT();
  const location = useLocation();
  const { onboarding } = useContainer();
  const profileQuery = useQuery({ queryKey: ["language-profile"], queryFn: () => onboarding.loadProfile() });
  const profile = profileQuery.data;
  useEffect(() => {
    if (location.hash === "#learning-preferences" && profile) {
      requestAnimationFrame(() => document.getElementById("learning-preferences")?.scrollIntoView({ block: "start" }));
    }
  }, [location.hash, profile]);
  const languagesQuery = useQuery({ queryKey: ["languages"], queryFn: () => onboarding.loadLanguages(), retry: false });
  // Language names follow the interface language ("Tiếng Anh"), not the English names from the server.
  const languageName = (code: string | null) => {
    const name = code ? languagesQuery.data?.find(language => language.code === code)?.name_en : null;
    return name ? t(name) : "—";
  };

  return (
    <section className="account-screen">
      <h1><T>Profile</T></h1>
      {profileQuery.isPending || languagesQuery.isPending ? <div className="pf-card pf-skel-group" role="status">
        <span className="sr-only"><T>Loading profile settings…</T></span>
        <div className="dl-skel pf-skel-line" aria-hidden="true" />
        <div className="dl-skel pf-skel-box" aria-hidden="true" />
      </div> : null}
      {profileQuery.isError || languagesQuery.isError ? <div role="alert" className="pf-card pf-card--alert"><p><T>Your profile settings could not be loaded.</T></p>
        <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => { void profileQuery.refetch(); void languagesQuery.refetch(); }}><T>Retry profile settings</T></button>
      </div> : null}
      <div className="pf-grid">
        <div className="pf-col">
          <IdentityCard profile={profile} languageName={languageName} />
          <StatsCard language={profile?.learning_language ?? null} />
          <SignOutButton />
        </div>
        <div className="pf-col">
          {profile && languagesQuery.data ? <LanguageSettings profile={profile} languages={languagesQuery.data.filter(language => language.is_active)} /> : null}
          <AppearanceCard />
          <section className="pf-card" aria-labelledby="pf-privacy-title">
            <h2 id="pf-privacy-title"><T>Voice and privacy</T></h2>
            <div className="pf-two"><VoiceBox /><TranscriptBox /></div>
            <div className="pf-rows"><TranscriptsRow /><AgentMemoryRow /><SignalsRow /></div>
          </section>
          <YourDataCard><DeleteAccountRow /></YourDataCard>
        </div>
      </div>
    </section>
  );
}

function IdentityCard({ profile, languageName }: { profile?: LearnerLanguageProfile; languageName: (code: string | null) => string }) {
  const t = useT();
  const { gateway } = useAuth();
  // The account has no display name yet, so the page shows the part of the email before "@".
  const email = useQuery({
    queryKey: ["account-email"],
    queryFn: async () => (await gateway.getClient().getSession()).data.session?.user.email ?? null,
    enabled: !!gateway,
    retry: false,
  }).data;
  return <section className="pf-card pf-identity" aria-label={t("Your account")}>
    <span className="pf-avatar"><Mascot state="happy" /></span>
    <strong>{email ? email.split("@")[0] : t("Your account")}</strong>
    {email ? <span className="pf-email">{email}</span> : null}
    {profile ? <div className="pf-tags">
      <span className="pf-tag pf-tag--hi">{t("Learning {language}", { language: languageName(profile.learning_language) })}{profile.declared_level ? ` · ${profile.declared_level}` : ""}</span>
      <span className="pf-tag">{t("Explained in {language}", { language: languageName(profile.support_language) })}</span>
    </div> : null}
  </section>;
}

function StatsCard({ language }: { language: string | null }) {
  const t = useT();
  const { progress } = useContainer();
  // Same key as the Progress page, so both read one cached copy.
  const query = useQuery({ queryKey: ["progress", "all"], queryFn: () => progress.loadProgress(), retry: false });
  const cards = query.data?.cards.filter(deck => language === null || deck.language_code === language);
  const stat = (value: number | undefined, label: string, highlight = false) =>
    <div className={`pf-stat${highlight ? " pf-stat--hi" : ""}`}><b>{value ?? "–"}</b><small>{label}</small></div>;
  return <section className="pf-card pf-stats" aria-label={t("Your numbers")}>
    {stat(query.data?.streak.current, t("Day streak"), true)}
    {stat(query.data?.streak.active_days, t("Days practised"))}
    {stat(cards?.reduce((sum, deck) => sum + deck.total, 0), t("Cards"))}
    {stat(cards?.reduce((sum, deck) => sum + deck.review, 0), t("Cards in review"))}
    <Link className="pf-stats__more" to="/progress"><T>See progress</T><span aria-hidden="true">›</span></Link>
  </section>;
}

function SignOutButton() {
  const { signOut } = useAuth();
  const navigate = useNavigate();
  return <button type="button" className="pf-signout" onClick={() => { signOut().then(() => navigate("/signin", { replace: true })).catch(() => {}); }}>
    <T>Sign out</T>
  </button>;
}

function Choices<V extends string>({ label, options, value, disabled, onChange }: {
  label: string; options: { value: V; label: string }[]; value: V; disabled: boolean; onChange: (value: V) => void;
}) {
  return <div className="pf-pills" role="group" aria-label={label}>
    {options.map(option => <button key={option.value} type="button" className="pf-pill" aria-pressed={value === option.value}
      disabled={disabled} onClick={() => onChange(option.value)}>{option.label}</button>)}
  </div>;
}

function LanguageSettings({ profile, languages }: { profile: LearnerLanguageProfile; languages: Language[] }) {
  const t = useT();
  const { onboarding } = useContainer();
  const queryClient = useQueryClient();
  const [learning, setLearning] = useState(profile.learning_language ?? "");
  const [support, setSupport] = useState(profile.support_language ?? "");
  const [level, setLevel] = useState(profile.declared_level ?? "");
  const [levelEdited, setLevelEdited] = useState(false);
  const levels = DECLARED_LEVELS[learning] ?? [];
  const valid = learning !== support && languages.some(language => language.code === learning)
    && languages.some(language => language.code === support);
  const changed = learning !== (profile.learning_language ?? "") || support !== (profile.support_language ?? "") || level !== (profile.declared_level ?? "");
  const save = useMutation({
    mutationFn: () => onboarding.saveProfile({ learningLanguageCode: learning, supportLanguageCode: support,
      ...(levelEdited || learning === profile.learning_language ? { declaredLevel: level } : {}) }),
    onSuccess: async updated => {
      queryClient.setQueryData(["language-profile"], updated);
      setLearning(updated.learning_language ?? ""); setSupport(updated.support_language ?? "");
      setLevel(updated.declared_level ?? ""); setLevelEdited(false);
      await queryClient.invalidateQueries();
    },
  });
  function submit(event: FormEvent) { event.preventDefault(); if (valid) save.mutate(); }
  function reset() {
    setLearning(profile.learning_language ?? ""); setSupport(profile.support_language ?? "");
    setLevel(profile.declared_level ?? ""); setLevelEdited(false); save.reset();
  }
  const languageOptions = languages.map(language => ({ value: language.code, label: t(language.name_en) }));
  return <form id="learning-preferences" className="pf-card" onSubmit={submit} aria-labelledby="pf-learning-title">
    <h2 id="pf-learning-title"><T>Learning settings</T></h2>
    <div className="pf-box">
      <span className="pf-box__label"><T>Learning language</T></span>
      <Choices label={t("Learning language")} options={languageOptions} value={learning} disabled={save.isPending} onChange={language => {
        setLearning(language); setLevel(language === profile.learning_language ? profile.declared_level ?? "" : ""); setLevelEdited(false);
      }} />
      <span className="pf-box__label"><T>Support language</T></span>
      <Choices label={t("Support language")} options={languageOptions} value={support} disabled={save.isPending} onChange={setSupport} />
      {learning === support ? <p className="pf-error" role="alert"><T>Choose different learning and support languages.</T></p> : null}
    </div>
    <div className="pf-box">
      <span className="pf-box__label"><T>My level</T></span>
      <Choices label={t("My level")} options={[{ value: "", label: t("Not set") }, ...levels.map(value => ({ value, label: value }))]}
        value={level} disabled={save.isPending} onChange={value => { setLevel(value); setLevelEdited(true); }} />
      <p className="pf-hint"><T>Your own estimate, not a test score. Used for word-level warnings and video coverage estimates.</T></p>
    </div>
    <div className="pf-actions">
      {save.isError ? <p className="pf-error" role="alert"><T>Your profile could not be saved. Please try again.</T></p> : null}
      {save.isSuccess && !changed ? <p className="pf-saved" role="status"><T>Profile saved.</T></p> : null}
      <button type="button" className="pf-link-btn" disabled={!changed || save.isPending} onClick={reset}><T>Cancel</T></button>
      <button type="submit" className="dl-btn dl-btn--primary dl-btn--sm" disabled={!valid || !changed || save.isPending}>{save.isPending ? <T>Saving…</T> : <T>Save profile</T>}</button>
    </div>
  </form>;
}
