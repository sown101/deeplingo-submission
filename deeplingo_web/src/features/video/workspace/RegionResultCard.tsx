import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { formatClock, type StudyRegionView } from "./workspaceModels";
import { resultLines } from "./regionResult";
import type { VideoPart } from "./videoParts";
import { T, useT } from "../../../i18n/i18n";

// The result of one study part, read back from the learner's log: it counts what was really done in this part.
// It opens in the watch page's right panel; talking about the part goes through the page's Tata launcher.
export function RegionResultCard({ libraryItemId, regionId, region, nextPart, busy, onStudyNext, onClose }: {
  libraryItemId: string;
  regionId: string;
  region: StudyRegionView;
  nextPart: VideoPart | null;
  busy: boolean;
  onStudyNext: (part: VideoPart) => void;
  onClose: () => void;
}) {
  const t = useT();
  const { playback } = useContainer();
  const ref = useRef<HTMLElement>(null);
  const query = useQuery({
    queryKey: ["region-result", libraryItemId, regionId],
    queryFn: () => playback.getRegionResult(libraryItemId, regionId),
    retry: false, staleTime: 0, gcTime: 0,
  });
  // On a phone the panel is below the player: bring the result into view.
  useEffect(() => { ref.current?.scrollIntoView?.({ block: "nearest" }); }, []);
  const lines = query.data ? resultLines(query.data, t) : [];
  return (
    <section ref={ref} className="region-result" aria-labelledby="region-result-title">
      <header className="region-result__head">
        <h2 id="region-result-title">
          <T v1={formatClock(region.start_ms)} v2={formatClock(region.end_ms)}>{"Result for {v1}–{v2}"}</T>
        </h2>
        <button type="button" className="dl-icon-btn region-result__close" aria-label={t("Close")} title={t("Close")} onClick={onClose}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
        </button>
      </header>
      {query.isPending ? <p role="status" className="muted"><T>Adding up your practice…</T></p> : null}
      {query.isError ? (
        <div role="alert" className="stack">
          <p><T>We could not load the result. Please try again.</T></p>
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => void query.refetch()}>
            <T>Try again</T>
          </button>
        </div>
      ) : null}
      {query.data ? (lines.length > 0 ? (
        <dl className="region-result__lines">
          {lines.map((line) => <div key={line.label}><dt>{line.label}</dt><dd>{line.value}</dd></div>)}
        </dl>
      ) : <p className="muted"><T>Nothing practised in this part yet.</T></p>) : null}
      <div className="region-result__actions">
        {nextPart ? (
          <button type="button" className="dl-btn dl-btn--primary" onClick={() => onStudyNext(nextPart)} disabled={busy}>
            <T v1={formatClock(nextPart.start_ms)} v2={formatClock(nextPart.end_ms)}>{"Next: {v1}–{v2}"}</T>
          </button>
        ) : <span className="muted small"><T>You reached the end of the video.</T></span>}
      </div>
    </section>
  );
}
