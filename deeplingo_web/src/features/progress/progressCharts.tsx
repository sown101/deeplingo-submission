import { useState, type PointerEvent } from "react";
import { T, useT } from "../../i18n/i18n";
import { localDay } from "../plan/planModels";
import type { ActivityDay, Deck, KindAccuracy, PronunciationDay, SpeakingWeek } from "./progressApi";

// Card states are ordered, so they share one hue from light to dark.
export const STATES = [
  { key: "new", label: "New" },
  { key: "learning", label: "Learning" },
  { key: "review", label: "Review" },
  { key: "relearning", label: "Relearning" },
] as const;

const shortDate = (date: string) => `${date.slice(8)}/${date.slice(5, 7)}`;

function noon(date: Date, shift = 0): Date {
  const day = new Date(date);
  day.setHours(12, 0, 0, 0);
  day.setDate(day.getDate() + shift);
  return day;
}

/** The Monday of the week holding `date`, as a local day key. */
const mondayOf = (date: Date) => localDay(noon(date, -((date.getDay() + 6) % 7)));

export interface Bar { key: string; label: string; value: number }

/** Actions on each of the last `count` days. */
export function dailyBars(days: ActivityDay[], count: number, today = new Date()): Bar[] {
  const counts = new Map(days.map(day => [day.date, day.attempts]));
  return Array.from({ length: count }, (_, index) => {
    const key = localDay(noon(today, index - count + 1));
    return { key, label: shortDate(key), value: counts.get(key) ?? 0 };
  });
}

/** Actions in each of the last `count` weeks (Monday to Sunday), the last one holding today. */
export function weeklyBars(days: ActivityDay[], count: number, today = new Date()): Bar[] {
  const sums = new Map<string, number>();
  for (const day of days) {
    const week = mondayOf(new Date(`${day.date}T12:00:00`));
    sums.set(week, (sums.get(week) ?? 0) + day.attempts);
  }
  const thisWeek = noon(today, -((today.getDay() + 6) % 7));
  return Array.from({ length: count }, (_, index) => {
    const key = localDay(noon(thisWeek, (index - count + 1) * 7));
    return { key, label: shortDate(key), value: sums.get(key) ?? 0 };
  });
}

/** Minutes of speaking in each of the last `count` weeks. */
export function speakingBars(weeks: SpeakingWeek[], count: number, today = new Date()): Bar[] {
  const minutes = new Map(weeks.map(week => [week.week_start, week.minutes]));
  const thisWeek = noon(today, -((today.getDay() + 6) % 7));
  return Array.from({ length: count }, (_, index) => {
    const key = localDay(noon(thisWeek, (index - count + 1) * 7));
    return { key, label: shortDate(key), value: minutes.get(key) ?? 0 };
  });
}

/** Vertical bars with the last one highlighted and, for activity, the average of the non-empty bars as a dashed line. */
export function BarChart({ bars, label, average = false, lastLabel }: { bars: Bar[]; label: string; average?: boolean; lastLabel: string }) {
  const t = useT();
  const peak = Math.max(1, ...bars.map(bar => bar.value));
  const filled = bars.filter(bar => bar.value);
  const mean = filled.length ? filled.reduce((sum, bar) => sum + bar.value, 0) / filled.length : 0;
  return <>
    <div className="progress-bars" role="img" aria-label={label}>
      {bars.map((bar, index) => <i key={bar.key} className={bar.value ? index === bars.length - 1 ? "today" : undefined : "zero"}
        style={{ height: `${Math.max(2, bar.value / peak * 100)}%` }} title={`${bar.label}: ${Math.round(bar.value * 10) / 10}`} />)}
      {average && mean ? <span className="progress-bars__avg" style={{ bottom: `${mean / peak * 100}%` }}><em>{t("Avg {n}", { n: Math.round(mean) })}</em></span> : null}
    </div>
    <div className="progress-axis" aria-hidden="true"><span>{bars[0].label}</span><span>{lastLabel}</span></div>
  </>;
}

/** Cards by FSRS state: one stacked bar per language, then the totals per state. */
export function CardsByState({ decks, name }: { decks: Deck[]; name: (code: string) => string }) {
  const t = useT();
  const sum = { total: 0, due: 0, new: 0, learning: 0, review: 0, relearning: 0 };
  for (const deck of decks) for (const key of Object.keys(sum) as (keyof typeof sum)[]) sum[key] += deck[key];
  return <>
    <p className="progress-total">{sum.total} <span><T>cards</T></span> · {sum.due} <span><T>due now</T></span></p>
    <div className="progress-decks">
      {decks.map(deck => <div key={deck.language_code} className="progress-deck">
        <span>{name(deck.language_code)}</span>
        <div className="progress-stack" role="img" aria-label={`${name(deck.language_code)}: ${STATES.map(state => `${t(state.label)} ${deck[state.key]}`).join(", ")}`}>
          {STATES.map((state, index) => deck[state.key] ? <i key={state.key} className={`progress-stage-${index}`} style={{ flexGrow: deck[state.key] }} title={`${t(state.label)}: ${deck[state.key]}`} /> : null)}
        </div>
        <strong>{deck.total}</strong>
      </div>)}
    </div>
    <ul className="progress-stages">
      {STATES.map((state, index) => <li key={state.key}><i className={`progress-stage-${index}`} aria-hidden="true" /><span>{t(state.label)}</span><strong>{sum[state.key]}</strong></li>)}
    </ul>
  </>;
}

/** Accuracy per exercise kind as horizontal bars. */
export function AccuracyBars({ items, kindLabel }: { items: KindAccuracy[]; kindLabel: (kind: string) => string }) {
  const t = useT();
  return <ul className="progress-accuracy">
    {items.map(item => <li key={item.kind}>
      <div><span>{kindLabel(item.kind)}</span><em>{t("{correct} of {n}", { correct: item.correct, n: item.attempts })}</em><strong>{Math.round(item.accuracy)}%</strong></div>
      <div className="progress-meter" aria-hidden="true"><i style={{ width: `${Math.max(2, item.accuracy)}%` }} /></div>
    </li>)}
  </ul>;
}

type Metric = "pronunciation" | "accuracy" | "fluency" | "completeness" | "prosody";
// Every sentence score Azure returns; prosody only for English.
const METRICS: { key: Metric; label: string; empty: string }[] = [
  { key: "pronunciation", label: "Pronunciation score", empty: "No score yet." },
  { key: "accuracy", label: "Accuracy", empty: "No score yet." },
  { key: "fluency", label: "Fluency", empty: "No score yet." },
  { key: "completeness", label: "Completeness", empty: "Shown from your next speaking practice." },
  { key: "prosody", label: "Prosody", empty: "Azure scores prosody only for English." },
];

const scored = (days: PronunciationDay[], key: Metric) =>
  days.flatMap(day => { const value = day[key]; return value === null ? [] : [{ date: day.date, value }]; });
const mean = (items: { value: number }[]) => items.reduce((sum, item) => sum + item.value, 0) / items.length;

/** How the last 7 days compare with the 7 before them, when both have scores. */
function weekChange(points: { date: string; value: number }[]): number | null {
  const since = (back: number) => { const date = new Date(); date.setDate(date.getDate() - back); return localDay(date); };
  const thisWeek = points.filter(point => point.date > since(7));
  const lastWeek = points.filter(point => point.date > since(14) && point.date <= since(7));
  return thisWeek.length && lastWeek.length ? Math.round(mean(thisWeek) - mean(lastWeek)) : null;
}

/** Each score in its own line chart by day, sessions per day beside them, the weakest words, and every value in one table for screen readers. */
export function PronunciationCharts({ days, weakWords, language }: { days: PronunciationDay[]; weakWords: string[]; language: string | null }) {
  const t = useT();
  return <>
    <div className="progress-metrics">
      {METRICS.map(metric => <MetricChart key={metric.key} days={days} metric={metric.key} label={t(metric.label)}
        empty={t(metric.key === "prosody" && language === "en" ? "Shown from your next speaking practice." : metric.empty)} />)}
      <SessionsChart days={days} />
    </div>
    <div className="progress-weak">
      <h3><T>Weakest words</T></h3>
      {weakWords.length ? <ul>{weakWords.map(word => <li key={word} lang={language ?? undefined}>{word}</li>)}</ul> : <p className="progress-muted"><T>No weak words yet.</T></p>}
    </div>
    <div className="sr-only"><table>
      <caption>{t("Pronunciation scores by day")}</caption>
      <thead><tr><th>{t("Date")}</th>{METRICS.map(metric => <th key={metric.key}>{t(metric.label)}</th>)}<th>{t("Sessions")}</th></tr></thead>
      <tbody>{days.map(item => <tr key={item.date}><td>{item.date}</td>
        {METRICS.map(metric => { const value = item[metric.key]; return <td key={metric.key}>{value === null ? "–" : Math.round(value)}</td>; })}
        <td>{item.sessions}</td></tr>)}</tbody>
    </table></div>
  </>;
}

/** One 0-100 score by day: the latest value and its weekly change above a line, the day's value on hover. */
function MetricChart({ days, metric, label, empty }: { days: PronunciationDay[]; metric: Metric; label: string; empty: string }) {
  const t = useT();
  const [active, setActive] = useState<number | null>(null);
  // Only the days that have this score are drawn.
  const points = scored(days, metric);
  if (points.length === 0) {
    return <div className={`progress-metric progress-metric--${metric}`}>
      <div className="progress-metric__head"><span>{label}</span><strong>–</strong><small>{empty}</small></div>
    </div>;
  }
  const x = (index: number) => points.length === 1 ? 50 : index / (points.length - 1) * 100;
  const shown = active ?? points.length - 1;
  const current = points[shown];
  const latest = points[points.length - 1];
  const change = weekChange(points);
  function track(event: PointerEvent<HTMLDivElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = box.width ? Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)) : 0;
    setActive(Math.round(ratio * (points.length - 1)));
  }
  const at = (left: number, top?: number): { left: string; top?: string } => ({ left: `${left}%`, ...(top === undefined ? {} : { top: `${top}%` }) });
  return <div className={`progress-metric progress-metric--${metric}`}>
    <div className="progress-metric__head">
      <span>{label}</span>
      <strong>{Math.round(latest.value)}</strong>
      <small>{latest.date === localDay() ? t("today") : t("on {date}", { date: shortDate(latest.date) })}
        {change !== null ? <> · <em className={change >= 0 ? "up" : "down"}>{t(change >= 0 ? "+{n} on the week before" : "{n} on the week before", { n: change })}</em></> : null}</small>
    </div>
    <div className="progress-plot" aria-hidden="true" onPointerMove={track} onPointerLeave={() => setActive(null)}>
      {[100, 50, 0].map(value => <span key={value} className="progress-gridline" style={{ top: `${100 - value}%` }}><em>{value}</em></span>)}
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline points={points.map((item, index) => `${x(index)},${100 - item.value}`).join(" ")} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      {active === null ? null : <i className="progress-crosshair" style={at(x(shown))} />}
      <i className="progress-dot" style={at(x(shown), 100 - current.value)} />
      {active === null ? null : <div className={`progress-tip${x(shown) > 60 ? " progress-tip--left" : ""}`} style={at(x(shown))}>
        <strong>{shortDate(current.date)}</strong>
        <span>{label} <b>{Math.round(current.value)}</b></span>
      </div>}
    </div>
    <div className="progress-axis" aria-hidden="true"><span>{shortDate(points[0].date)}</span>{points.length > 1 ? <span>{shortDate(points[points.length - 1].date)}</span> : null}</div>
  </div>;
}

/** Speaking sessions on each day that has a score. */
function SessionsChart({ days }: { days: PronunciationDay[] }) {
  const t = useT();
  const peak = Math.max(1, ...days.map(day => day.sessions));
  const total = days.reduce((sum, day) => sum + day.sessions, 0);
  return <div className="progress-metric progress-metric--sessions">
    <div className="progress-metric__head">
      <span><T>Speaking sessions</T></span>
      <strong>{total}</strong>
      <small>{t("on {n} days", { n: days.length })}</small>
    </div>
    <div className="progress-sessions" aria-hidden="true">
      {days.map(day => <i key={day.date} style={{ height: `${day.sessions / peak * 100}%` }} title={`${shortDate(day.date)}: ${day.sessions}`} />)}
    </div>
    <div className="progress-axis" aria-hidden="true"><span>{shortDate(days[0].date)}</span>{days.length > 1 ? <span>{shortDate(days[days.length - 1].date)}</span> : null}</div>
  </div>;
}
