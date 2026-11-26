import type { ReactNode } from "react";
import type { VideoPart } from "./videoParts";
import { formatClock, type RegionPreparationView } from "./workspaceModels";
import { T, useT } from "../../../i18n/i18n";

export const partKey = (part: { start_segment_id: string; end_segment_id: string }) =>
  `${part.start_segment_id}-${part.end_segment_id}`;

// The video's parts as a strip sized by length, the current part's details, and its actions.
export function PartsBar({ parts, current, region, busy, onChange, onFinish, note }: {
  parts: VideoPart[];
  current: VideoPart | undefined;
  region: { start_ms: number; end_ms: number; segment_count: number };
  busy: boolean;
  onChange: (key: string) => void;
  onFinish: () => void;
  note: ReactNode;
}) {
  const t = useT();
  const index = current ? parts.findIndex((part) => partKey(part) === partKey(current)) : -1;
  const step = (offset: number) => {
    const next = parts[index + offset];
    if (next) onChange(partKey(next));
  };
  return <div className="parts-bar">
    {parts.length > 1 ? <>
      <div className="parts-bar__head">
        <span className="parts-bar__label"><T>Study part</T></span>
        {index >= 0 ? <span className="parts-bar__count">{t("Part {n} of {total}", { n: index + 1, total: parts.length })}</span> : null}
      </div>
      <div className="parts-strip" role="group" aria-label={t("Change part")}>
        {parts.map((part, position) => {
          const on = index === position;
          return <button key={partKey(part)} type="button" className="parts-strip__part" aria-pressed={on} disabled={busy}
            style={{ flexGrow: Math.max(1, part.end_ms - part.start_ms) }}
            aria-label={t("Part {n}: {title} ({time})", { n: position + 1, title: part.title ?? t("Study part"), time: formatClock(part.start_ms) })}
            title={`${formatClock(part.start_ms)}${part.title ? ` · ${part.title}` : ""}`}
            onClick={() => { if (!on) onChange(partKey(part)); }}>{position + 1}</button>;
        })}
      </div>
    </> : null}
    <div className="parts-bar__current">
      {parts.length > 1 ? <button type="button" className="parts-bar__nav" aria-label={t("Previous part")} disabled={busy || index <= 0} onClick={() => step(-1)}>‹</button> : null}
      <span className="parts-bar__info">
        <strong>{current?.title ?? <T>Study part</T>}</strong>
        <small>{formatClock(region.start_ms)}–{formatClock(region.end_ms)} ·{" "}
          <T n={region.segment_count}>{region.segment_count === 1 ? "{n} sentence" : "{n} sentences"}</T>{note}</small>
      </span>
      {parts.length > 1 ? <button type="button" className="parts-bar__nav" aria-label={t("Next part")} disabled={busy || index < 0 || index >= parts.length - 1} onClick={() => step(1)}>›</button> : null}
      <span className="parts-bar__actions">
        <button type="button" className="dl-btn dl-btn--primary dl-btn--sm" onClick={onFinish}><T>Finish</T></button>
      </span>
    </div>
  </div>;
}

// Readiness of the part's words and questions. Watching, Dictation and Shadowing never wait for it.
export function PreparationNote({ preparation, busy, onRetry }: {
  preparation: RegionPreparationView | null;
  busy: boolean;
  onRetry: () => void;
}) {
  if (!preparation) return null;
  const retry = (
    <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={onRetry} disabled={busy}>
      <T>Try again</T>
    </button>
  );
  switch (preparation.status) {
    case "pending":
    case "processing":
      return <span className="preparation-note muted" role="status"> <T>· Preparing words for this part…</T></span>;
    case "ready":
      return <span className="preparation-note" role="status"> <T>· Words ready</T></span>;
    case "no_content":
      return <span className="preparation-note muted" role="status"> <T>· No new words to learn here</T></span>;
    case "budget_exhausted":
      return (
        <span className="preparation-note muted" role="status">
          {" "}
          <T>· You have prepared many parts today. You can still watch and practise</T>
          {preparation.reset_at ? `; more parts after ${new Date(preparation.reset_at).toLocaleTimeString()}` : ""}.
        </span>
      );
    case "failed":
      return (
        <span className="preparation-note muted" role="status">
          {" "}
          <T>· We could not prepare words for this part.</T>{preparation.retryable ? " " : ""}
          {preparation.retryable ? retry : null}
        </span>
      );
    case "unavailable":
      return (
        <span className="preparation-note muted" role="status">
          {" "}
          <T>· Word preparation is unavailable right now.</T> {retry}
        </span>
      );
    case "busy":
      return (
        <span className="preparation-note muted" role="status">
          {" "}
          <T>· Many parts are being prepared right now. You can still watch and practise.</T> {retry}
        </span>
      );
    default:
      return null;
  }
}
