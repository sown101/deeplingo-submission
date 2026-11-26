import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useContainer } from "../../app/container";
import { T, useT } from "../../i18n/i18n";
import { activityFacts, HeatmapLegend, YearHeatmap } from "./activityCharts";
import { AccuracyBars, BarChart, CardsByState, dailyBars, PronunciationCharts, speakingBars, weeklyBars } from "./progressCharts";
import "../home/home.css";
import "./progress.css";

const PERIODS = [
  { label: "1 month", days: 30, weeks: 5 },
  { label: "3 months", days: 91, weeks: 13 },
  { label: "1 year", days: 365, weeks: 53 },
];
const BAR_DAYS = 30;
const BAR_WEEKS = 26;
const SPEAKING_WEEKS = 12;
const KIND_LABELS: Record<string, string> = {
  flashcard: "Flashcard", choice: "Choice", cloze: "Fill in the blank", listening: "Listening", dictation: "Dictation",
  pronunciation: "Pronunciation", shadowing: "Shadowing", writing: "Writing", grammar_exercise: "Grammar exercises",
  region_question: "Video questions", roleplay: "Role play", match: "Match pairs", order: "Order the sentence",
};

/** The language's own name in the interface language, or its code when the browser does not know it. */
function languageName(code: string, locale: string): string {
  try { return new Intl.DisplayNames([locale], { type: "language" }).of(code) ?? code; } catch { return code; }
}

export function ProgressScreen() {
  const t = useT();
  const { progress } = useContainer();
  const [period, setPeriod] = useState(PERIODS[2]);
  const [language, setLanguage] = useState<string | null>(null);
  const [bars, setBars] = useState<"days" | "weeks">("days");
  const query = useQuery({
    queryKey: ["progress", language ?? "all"],
    queryFn: () => progress.loadProgress(language ?? undefined),
    placeholderData: keepPreviousData,
    retry: false,
  });
  const data = query.data;
  const [knownLanguages, setKnownLanguages] = useState<string[]>([]);
  useEffect(() => {
    if (!data?.languages.length) return;
    setKnownLanguages((prev) => {
      const merged = [...prev];
      for (const code of data.languages) {
        if (!merged.includes(code)) merged.push(code);
      }
      return merged.length === prev.length ? prev : merged;
    });
  }, [data?.languages]);
  const languages = knownLanguages.length ? knownLanguages : (data?.languages ?? []);
  const facts = data ? activityFacts(data.calendar, period.days) : null;
  const locale = t("en-US");

  return <section className="home-screen progress-screen">
    <div className="progress-top">
      <h1><T>Progress</T></h1>
      <div className="progress-periods" role="group" aria-label={t("Period")}>
        {PERIODS.map(item => <button key={item.label} type="button" aria-pressed={item === period} onClick={() => setPeriod(item)}>{t(item.label)}</button>)}
      </div>
    </div>
    {languages.length > 1 || language ? <div className="progress-periods progress-languages" role="group" aria-label={t("Language")}>
      <button type="button" aria-pressed={language === null} onClick={() => setLanguage(null)}>{t("All languages")}</button>
      {languages.map(code => <button key={code} type="button" aria-pressed={language === code} onClick={() => setLanguage(code)}>{languageName(code, locale)}</button>)}
    </div> : null}

    {query.isError ? <div role="alert" className="progress-alert">
      <p><T>Your progress could not be loaded.</T></p>
      <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => void query.refetch()}><T>Retry progress</T></button>
    </div> : null}

    <div className="progress-stats dl-stagger">
      <Stat label={t("Current streak")} value={data?.streak.current} unit={t("days")} note={t("Practise today to keep it going")} highlight />
      <Stat label={t("Longest streak")} value={facts?.longest} unit={t("days")} note={t("in this period")} />
      <Stat label={t("Days practised")} value={facts?.share} unit="%" note={facts ? t("{n} of {total} days", { n: facts.activeDays, total: facts.days }) : ""} />
      <Stat label={t("Speaking time")} value={data?.speaking.minutes} unit={t("minutes")} note={data ? t("{n} speaking sessions in the last 12 months", { n: data.speaking.sessions }) : ""} />
    </div>

    <section className="dl-card progress-card" aria-label={t("Activity")}>
      <div className="progress-card__head">
        <h2><T>Activity</T></h2>
        {facts ? <span>{t("{n} actions on {days} days", { n: facts.total, days: facts.activeDays })}</span> : null}
      </div>
      {data ? <>
        <YearHeatmap key={period.weeks} calendar={data.calendar} maxWeeks={period.weeks} large />
        <div className="progress-legend"><HeatmapLegend /></div>
      </> : null}
    </section>

    <section className="dl-card progress-card" aria-label={t("Activity over time")}>
      <div className="progress-card__head">
        <h2><T>Activity over time</T></h2>
        <div className="progress-periods" role="group" aria-label={t("Chart range")}>
          <button type="button" aria-pressed={bars === "days"} onClick={() => setBars("days")}>{t("Days")}</button>
          <button type="button" aria-pressed={bars === "weeks"} onClick={() => setBars("weeks")}>{t("Weeks")}</button>
        </div>
      </div>
      {data ? bars === "days"
        ? <BarChart bars={dailyBars(data.calendar.days, BAR_DAYS)} average label={t("Actions on each of the last {n} days", { n: BAR_DAYS })} lastLabel={t("Today")} />
        : <BarChart bars={weeklyBars(data.calendar.days, BAR_WEEKS)} average label={t("Actions in each of the last {n} weeks", { n: BAR_WEEKS })} lastLabel={t("This week")} /> : null}
    </section>

    <div className="progress-grid dl-stagger">
      <section className="dl-card progress-card" aria-label={t("Cards")}>
        <div className="progress-card__head"><h2><T>Cards</T></h2><Link to="/review/quick"><T>Review now</T> ›</Link></div>
        {data ? <CardsByState decks={data.cards} name={code => languageName(code, locale)} /> : null}
      </section>
      <section className="dl-card progress-card" aria-label={t("Accuracy")}>
        <div className="progress-card__head"><h2><T>Accuracy</T></h2><span><T>by exercise</T></span></div>
        {data && data.accuracy.length === 0 ? <p className="progress-muted"><T>Do an exercise to see your accuracy here.</T></p> : null}
        {data && data.accuracy.length ? <AccuracyBars items={data.accuracy} kindLabel={kind => t(KIND_LABELS[kind] ?? kind)} /> : null}
      </section>
      <section className="dl-card progress-card" aria-label={t("Grammar")}>
        <div className="progress-card__head"><h2><T>Grammar</T></h2></div>
        {data ? <ul className="progress-stages progress-rows">
          <li><span><T>Points learned</T></span><em /><strong>{data.grammar.learned}</strong></li>
          <li><span><T>Points done correctly</T></span><em /><strong>{data.grammar.done_correctly}</strong></li>
        </ul> : null}
      </section>
      <section className="dl-card progress-card" aria-label={t("Video")}>
        <div className="progress-card__head"><h2><T>Video</T></h2></div>
        {data ? <p className="progress-total">{data.regions_completed} <span><T>study regions practised</T></span></p> : null}
      </section>
      <section className="dl-card progress-card progress-card--wide" aria-label={t("Speaking per week")}>
        <div className="progress-card__head"><h2><T>Speaking per week</T></h2><span>{t("Last {n} weeks", { n: SPEAKING_WEEKS })}</span></div>
        {data && data.speaking.weeks.length === 0 ? <p className="progress-muted"><T>Speak with Tata to see your speaking time here.</T></p>
          : data ? <BarChart bars={speakingBars(data.speaking.weeks, SPEAKING_WEEKS)} label={t("Minutes of speaking in each of the last {n} weeks", { n: SPEAKING_WEEKS })} lastLabel={t("This week")} /> : null}
      </section>
    </div>

    <section className="dl-card progress-card" aria-label={t("Pronunciation")}>
      <div className="progress-card__head"><h2><T>Pronunciation</T></h2><span><T>score by day</T></span></div>
      {data && data.pronunciation.length === 0 ? <p className="progress-muted"><T>Speak with Tata to see your pronunciation here.</T></p>
        : data ? <PronunciationCharts days={data.pronunciation} weakWords={data.weak_words} language={language} /> : null}
    </section>
  </section>;
}

function Stat({ label, value, unit, note, highlight = false }: { label: string; value?: number; unit: string; note: string; highlight?: boolean }) {
  return <div className={`dl-card progress-stat${highlight ? " progress-stat--hi" : ""}`}>
    <small>{label}</small>
    <strong>{value ?? "–"}<span>{unit}</span></strong>
    <em>{note}</em>
  </div>;
}
