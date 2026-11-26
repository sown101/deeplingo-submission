import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { parseSessionAnalysis, type AnalysisReference } from "./sessionAnalysisModels";
import { T, useT } from "../../i18n/i18n";

export function SessionAnalysis({ analysis }: { analysis: AnalysisReference }) {
  const t = useT();
  const { client } = useContainer();
  const cache = useQueryClient();
  const started = useRef(Date.now());
  const query = useQuery({
    queryKey: ["speaking-analysis", analysis.session_id],
    queryFn: async () => parseSessionAnalysis(await client.get<unknown>(`/learner/me/speaking-sessions/${analysis.session_id}`)),
    enabled: analysis.status !== "unavailable",
    retry: 1,
    refetchInterval: (q) => ["queued", "processing", "projecting"].includes(q.state.data?.status ?? analysis.status)
      && Date.now() - started.current < 15 * 60_000 ? 1000 : false,
  });
  const view = query.data, status = view?.status ?? analysis.status;
  useEffect(() => {
    if (view?.status === "completed") {
      void cache.invalidateQueries({ queryKey: ["my-words"] });
      void cache.invalidateQueries({ queryKey: ["video-coverage"] });
    }
  }, [cache, view]);
  return <section className="stack" aria-label={t("Speaking practice update")}>
    <h2><T>Speaking practice update</T></h2>
    {query.isError ? <div role="alert"><p><T>Your speaking update could not be loaded.</T></p>
      <button className="dl-btn dl-btn--secondary" onClick={() => void query.refetch()}><T>Retry</T></button></div>
      : status === "queued" || status === "processing" || status === "projecting" ? <p role="status"><T>Reviewing how you used your saved words…</T></p>
      : status === "completed" ? view && view.events.length > 0 ? <ul>{view.events.map((event) =>
        <li key={event.concept_id}><strong>{event.text}</strong> · {event.kind === "framed_use" ? <T>Used with support</T> : <T>Used independently</T>}</li>)}
        </ul> : <p><T>No reliable word use was confirmed in this session.</T></p>
      : <p><T>Your speaking update could not be completed. You can continue practising.</T></p>}
  </section>;
}
