import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { useT } from "../../../i18n/i18n";
import { useModalDialog } from "../../../lib/modalA11y";
import type { GrammarScope } from "./grammarModels";

export function GrammarSheet({ libraryItemId, segmentId, span, initialScope, supportLanguage, onClose }: {
  libraryItemId: string; segmentId: string; span: { start: number; end: number }; initialScope: GrammarScope;
  supportLanguage: string; onClose: () => void;
}) {
  const t = useT();
  const { playback } = useContainer();
  const ref = useModalDialog(onClose);
  const [scope, setScope] = useState(initialScope);
  const query = useQuery({
    queryKey: ["transcript-grammar", libraryItemId, segmentId, span.start, span.end, scope, supportLanguage],
    queryFn: () => playback.explainGrammar(libraryItemId, segmentId, span, scope),
    retry: false, staleTime: Infinity, refetchOnWindowFocus: false, refetchOnReconnect: false,
  });
  const data = query.data;
  return <div className="dialog-backdrop">
    <div ref={ref} className="card dialog concept-sheet" role="dialog" aria-modal="true"
      aria-labelledby="grammar-sheet-title" tabIndex={-1}>
      <div className="row between">
        <h2 id="grammar-sheet-title">{t("Grammar explanation")}</h2>
        <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={onClose} aria-label={t("Close grammar explanation")}>{t("Close")}</button>
      </div>
      {query.isLoading ? <p role="status">{t("Analysing the selected part…")}</p> : null}
      {query.isError ? <div>
        <p role="alert">{t("This part could not be explained. Choose a shorter part or try again.")}</p>
        <button type="button" className="dl-btn dl-btn--secondary" onClick={() => void query.refetch()}>{t("Retry")}</button>
      </div> : null}
      {data ? <>
        <blockquote>{data.source_text}</blockquote>
        <p className="small muted" role="note">{data.source === "ai_unverified"
          ? t("AI explanation, unverified") : t("Prepared content, not yet approved")}</p>
        {(["sentence_structure", "grammar", "important_words"] as const).map(key => <section key={key}>
          <h3>{data.explanation[key].title}</h3>
          <p style={{ whiteSpace: "pre-line" }}>{data.explanation[key].text}</p>
        </section>)}
      </> : null}
      {scope === "selection" ? <button type="button" className="dl-btn dl-btn--secondary" disabled={query.isLoading}
        onClick={() => setScope("sentence")}>{t("Analyse the whole sentence")}</button> : null}
    </div>
  </div>;
}
