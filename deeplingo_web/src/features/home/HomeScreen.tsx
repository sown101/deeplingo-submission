import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useContainer } from "../../app/container";
import { localDay, planItemPath, type PlanItem } from "../plan/planModels";
import { T, useT } from "../../i18n/i18n";
import { HomeEvidence } from "./HomeEvidence";
import type { Progress } from "../progress/progressApi";
import "./home.css";
import { Mascot } from "../../design/Mascot";
import { VideoLibrary } from "../library/VideoLibrary";

// What to do next is proposed by the agent in conversation; Home shows the video in progress and the learner's own record.
export function HomeScreen() {
  const { plan, progress } = useContainer();
  const t = useT();
  const day = localDay();
  const planQuery = useQuery({ queryKey: ["home", "plan", day], queryFn: () => plan.today(day), retry: false });
  // Secondary: its failure never blocks the suggestions.
  const progressQuery = useQuery({ queryKey: ["progress", "all"], queryFn: () => progress.loadProgress(), retry: false });
  const hour = new Date().getHours();

  return (
    <section className="home-screen" aria-busy={planQuery.isPending}>
      <header className="home-head">
        <div className="home-head-text">
          <span className="home-date">{new Intl.DateTimeFormat(t("en-US"), { weekday: "long", day: "numeric", month: "long" }).format(new Date())}</span>
          <h1 aria-label={t("Home")}>{t(hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening")}</h1>
        </div>

      </header>

      {planQuery.isPending ? <HomeLoading /> : null}
      {planQuery.isError ? (
        <div className="home-error" role="alert">
          <p><T>Your suggestions could not be loaded.</T></p>
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => void planQuery.refetch()}><T>Retry suggestions</T></button>
        </div>
      ) : null}
      {planQuery.data ? <Today items={planQuery.data.items} progress={progressQuery.data} progressFailed={progressQuery.isError} retryProgress={() => void progressQuery.refetch()} /> : null}
      {/* The Library screen was folded into Home: the learner's videos and the link form live here. */}
      <VideoLibrary />
    </section>
  );
}

function HomeLoading() {
  return <div role="status">
    <span className="sr-only"><T>Preparing your suggestions…</T></span>
    <div className="home-loading" aria-hidden="true">
      <div className="dl-card home-featured">
        <div className="home-featured-row"><div className="dl-skel home-hero-mascot home-loading-avatar" />
          <div className="home-loading-copy"><div className="dl-skel" /><div className="dl-skel" /><div className="dl-skel" /></div>
        </div>
        <div className="dl-skel home-loading-button" />
      </div>
      <div className="dl-card home-loading-evidence">
        <div className="dl-skel" /><div className="dl-skel" /><div className="dl-skel" />
      </div>
    </div>
  </div>;
}

function Today({ items, progress, progressFailed, retryProgress }: { items: PlanItem[]; progress?: Progress; progressFailed: boolean; retryProgress: () => void }) {
  const { plan } = useContainer();
  const t = useT();
  const navigate = useNavigate();
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const video = hidden ? undefined : items.find((item) => item.status === "open" && item.kind === "video_practice");

  async function resume(item: PlanItem) {
    setBusy(true);
    try {
      await plan.accept(item.id);
    } catch {
      // Recording the choice is secondary: the learner goes on either way.
    }
    navigate(planItemPath(item));
  }

  async function later(item: PlanItem) {
    setBusy(true);
    try {
      await plan.dismiss(item.id);
      setHidden(true);
    } catch {
      // Keep it on screen; the learner can try again.
    } finally {
      setBusy(false);
    }
  }

  return <div className="home-dashboard">
    {video ? <section className="dl-card home-featured" aria-label={t("Resume watching")}>
      <div className="home-featured-row">
        <Mascot className="home-hero-mascot" />
        <div className="home-card-text">
          <span className="dl-card__eyebrow"><T>Resume watching</T></span>
          <h2 className="dl-card__title">{video.video_title || t("Watch a video")}</h2>
        </div>
      </div>
      <button type="button" className="dl-btn dl-btn--primary dl-btn--lg home-resume" disabled={busy}
        onClick={() => void resume(video)}><T>Resume this video</T></button>
      <button type="button" className="home-dismiss" disabled={busy} aria-label={t("Not today")} title={t("Not today")} onClick={() => void later(video)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="m8 8 8 8m0-8-8 8" /></svg>
      </button>
    </section> : null}
    <div className="home-context"><HomeEvidence progress={progress} failed={progressFailed} retry={retryProgress} /></div>
  </div>;
}
