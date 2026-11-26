import { useEffect, useRef, useState, type CSSProperties } from "react";
import { T, useT } from "../../i18n/i18n";
import { localDay } from "../plan/planModels";
import type { ActivityCalendar } from "./progressApi";
import "./activity.css";

const MAX_WEEKS = 53;
const DAY_LABEL_ROOM = 28;

type Cell = { key: string; date: Date; attempts: number } | null;

function noon(date: Date, shift = 0): Date {
  const day = new Date(date);
  day.setHours(12, 0, 0, 0);
  day.setDate(day.getDate() + shift);
  return day;
}

/** Monday-to-Sunday weeks, the last one holding today; days after today are left empty. */
function weeksEndingToday(today: Date, weeks: number, attempts: Map<string, number>): Cell[][] {
  const first = noon(today, -((today.getDay() + 6) % 7) - (weeks - 1) * 7);
  const end = localDay(today);
  return Array.from({ length: weeks }, (_, week) => Array.from({ length: 7 }, (_, day) => {
    const date = noon(first, week * 7 + day);
    const key = localDay(date);
    return key > end ? null : { key, date, attempts: attempts.get(key) ?? 0 };
  }));
}

function level(attempts: number, peak: number) {
  return attempts === 0 ? 0 : Math.min(4, Math.ceil(attempts / peak * 4));
}

export interface ActivityFacts {
  days: number;
  activeDays: number;
  total: number;
  longest: number;
  share: number;
  average: number;
  current: number;
}

/** Streaks, share of days and average over the last `days` days; the current streak is the server's. */
export function activityFacts(calendar: ActivityCalendar, days: number, today = new Date()): ActivityFacts {
  const attempts = new Map(calendar.days.map(day => [day.date, day.attempts]));
  const counts = Array.from({ length: days }, (_, index) => attempts.get(localDay(noon(today, index - days + 1))) ?? 0);
  let longest = 0;
  let run = 0;
  for (const count of counts) {
    run = count ? run + 1 : 0;
    longest = Math.max(longest, run);
  }
  const activeDays = counts.filter(Boolean).length;
  const total = counts.reduce((sum, count) => sum + count, 0);
  return {
    days, activeDays, total, longest,
    share: Math.round(activeDays / days * 100),
    average: activeDays ? Math.round(total / activeDays) : 0,
    current: calendar.current_streak_days,
  };
}

/** A calendar heatmap that shows as many weeks as fit its width, up to `maxWeeks`. */
export function YearHeatmap({ calendar, maxWeeks = MAX_WEEKS, large = false }: { calendar: ActivityCalendar; maxWeeks?: number; large?: boolean }) {
  const t = useT();
  const box = useRef<HTMLDivElement>(null);
  const [weeks, setWeeks] = useState(maxWeeks);
  useEffect(() => {
    const node = box.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const fit = () => {
      if (!node.clientWidth) return;
      const style = getComputedStyle(node);
      const cell = parseFloat(style.getPropertyValue("--cell")) || 13;
      const gap = parseFloat(style.getPropertyValue("--gap")) || 3;
      setWeeks(Math.max(4, Math.min(maxWeeks, Math.floor((node.clientWidth - DAY_LABEL_ROOM + gap) / (cell + gap)))));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(node);
    return () => observer.disconnect();
  }, [maxWeeks]);

  const grid = weeksEndingToday(new Date(), weeks, new Map(calendar.days.map(day => [day.date, day.attempts])));
  const cells = grid.flat().filter(cell => cell !== null);
  const peak = Math.max(1, ...cells.map(cell => cell.attempts));
  const total = cells.reduce((sum, cell) => sum + cell.attempts, 0);
  const locale = t("en-US");
  const month = new Intl.DateTimeFormat(locale, { month: "short" });
  // Vietnamese month names are long ("Tháng 11"), so the heatmap uses the short form "Th11".
  const monthName = (date: Date) => locale.startsWith("vi") ? `Th${date.getMonth() + 1}` : month.format(date);
  const weekday = new Intl.DateTimeFormat(locale, { weekday: locale.startsWith("vi") ? "narrow" : "short" });
  const todayKey = localDay();
  // A month is named over the week holding its first day; the first week only when no month starts soon after.
  const starts = grid.map(week => week.find(cell => cell?.date.getDate() === 1) ?? null);
  const months = grid.map((week, index) => {
    const first = starts[index] ?? (index === 0 && !starts.slice(1, 4).some(Boolean) ? week[0] : null);
    return first ? monthName(first.date) : "";
  });
  const style = { "--weeks": weeks } as CSSProperties;
  return <div ref={box} className={`act-heatmap${large ? " act-heatmap--large" : ""}`} style={style}>
    <div className="act-heatmap__months" aria-hidden="true">{months.map((name, index) => name ? <span key={index} style={{ gridColumn: index + 1 }}>{name}</span> : null)}</div>
    <div className="act-heatmap__days" aria-hidden="true">{[0, 2, 4].map(day => <span key={day} style={{ gridRow: day + 1 }}>{weekday.format(noon(grid[0][0]?.date ?? new Date(), day))}</span>)}</div>
    <div className="act-heatmap__grid" role="img" aria-label={t("{n} practice attempts in the last {weeks} weeks", { n: total, weeks })}>
      {grid.map(week => week.map((cell, day) => cell
        ? <i key={cell.key} className={`act-cell level-${level(cell.attempts, peak)}${cell.key === todayKey ? " today" : ""}`} title={`${cell.key}: ${cell.attempts}`} />
        : <i key={`empty-${day}`} className="act-cell empty" />))}
    </div>
  </div>;
}

export function HeatmapLegend() {
  return <div className="act-legend" aria-hidden="true"><T>Less</T>{[0, 1, 2, 3, 4].map(n => <i key={n} className={`act-cell level-${n}`} />)}<T>More</T></div>;
}
