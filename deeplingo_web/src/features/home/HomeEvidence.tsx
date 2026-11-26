import { Link } from "react-router-dom";
import { T, useT } from "../../i18n/i18n";
import { activityFacts, HeatmapLegend, YearHeatmap } from "../progress/activityCharts";
import type { Progress } from "../progress/progressApi";
import type { MyWord } from "../words/wordsModels";

/** Saved words whose review time has come, longest overdue first. */
export function dueWords(words: MyWord[], now: Date) {
  return words
    .filter(word => word.saved && word.status === "active" && word.nextReviewAt !== null && new Date(word.nextReviewAt) <= now)
    .sort((a, b) => a.nextReviewAt!.localeCompare(b.nextReviewAt!));
}

// One card: a year of practice on the left (it opens Progress), the learner's cards by state on the right.
export function HomeEvidence({ progress, failed, retry }: { progress?: Progress; failed: boolean; retry: () => void }) {
  const t = useT();
  const calendar = progress?.calendar;
  const facts = calendar ? activityFacts(calendar, 365) : null;
  const total = progress?.cards.reduce((sum, deck) => sum + deck.total, 0) ?? 0;
  const due = progress?.cards.reduce((sum, deck) => sum + deck.due, 0) ?? 0;
  const states = (["new", "learning", "review", "relearning"] as const).map(key => ({ key, count: progress?.cards.reduce((sum, deck) => sum + deck[key], 0) ?? 0 }));

  return <section className="dl-card home-activity-card">
    <div className="home-activity" aria-label={t("Activity")} role="group">
      {failed ? <div className="home-secondary-state"><p><T>Your activity could not be loaded.</T></p><button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={retry}><T>Retry</T></button></div>
        : !calendar || !facts ? <div className="home-skeleton home-skeleton-chart" aria-label={t("Loading activity…")} />
        : <>
          <Link to="/progress" className="home-activity__map" aria-label={t("Open Progress")}><YearHeatmap calendar={calendar} /></Link>
          <div className="home-activity__foot">
            <p className="act-facts">
              <T>Current streak</T> <b className="hi">{t("{n} days", { n: calendar.current_streak_days })}</b> · <T>Longest</T> <b>{t("{n} days", { n: facts.longest })}</b> · <T>Practised on</T> <b>{facts.share}%</b> <T>of days</T> · <T>Average</T> <b>{facts.average}</b>{t("/day")}
            </p>
            <HeatmapLegend />
          </div>
        </>}
    </div>
    <span className="home-activity__divider" aria-hidden="true" />
    <div className="home-due" aria-label={t("Cards")} role="group">
      <div className="home-due__head">
        <span><b><T>Cards</T></b><small>{progress ? t("{n} due now", { n: due }) : ""}</small></span>
        <Link className="dl-btn dl-btn--primary dl-btn--sm home-due-action" to="/review/quick"><T>Review now</T></Link>
      </div>
      {failed ? null : !progress ? <div className="home-skeleton home-skeleton-chart" aria-label={t("Loading cards…")} />
        : <ul className="home-cards" aria-label={t("{n} cards", { n: total })}>
          {states.map(state => <li key={state.key}><span>{t(STATE_LABELS[state.key])}</span><b>{state.count}</b></li>)}
        </ul>}
    </div>
  </section>;
}

const STATE_LABELS = { new: "New", learning: "Learning", review: "Review", relearning: "Relearning" } as const;
