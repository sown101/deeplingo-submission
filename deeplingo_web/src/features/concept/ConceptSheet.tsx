import { useQuery } from "@tanstack/react-query";
import { useModalDialog } from "../../lib/modalA11y";
import { Icon } from "../../design/Icon";
import { useContainer } from "../../app/container";
import { WordActions } from "../words/WordActions";
import { T, useT } from "../../i18n/i18n";

// Modal Concept sheet. Semantics (shared useModalDialog): focus moves into
// the dialog on open, Tab cycles inside, Escape closes, focus returns to the
// element that opened it. The sheet never mutates learner state; "Add to my words" is only a practice-priority request.
export function ConceptSheet({
  libraryItemId,
  regionId,
  learningObjectId,
  onClose,
}: {
  libraryItemId: string;
  regionId?: string;
  learningObjectId: string;
  onClose: () => void;
}) {
  const t = useT();
  const { playback } = useContainer();
  const dialogRef = useModalDialog(onClose);

  const conceptQuery = useQuery({
    queryKey: ["concept", libraryItemId, learningObjectId],
    queryFn: () => playback.getConcept(libraryItemId, learningObjectId),
    retry: false,
  });

  return (
    <div className="dialog-backdrop">
      <div
        ref={dialogRef}
        className="card dialog concept-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="concept-sheet-title"
        tabIndex={-1}
      >
        <div className="row between">
          <h2 id="concept-sheet-title"><T>Concept</T></h2>
          <button type="button" className="dl-icon-btn" onClick={onClose} aria-label={t("Close")} title={t("Close")}>
            <Icon name="close" />
          </button>
        </div>

        {conceptQuery.isLoading ? <p role="status"><T>Loading concept…</T></p> : null}

        {conceptQuery.isError ? (
          <div>
            <p className="error" role="alert">
              <T>This concept could not be loaded. Please try again.</T>
            </p>
            <button type="button" className="dl-btn dl-btn--secondary" onClick={() => conceptQuery.refetch()}>
              <T>Retry</T>
            </button>
          </div>
        ) : null}

        {conceptQuery.data ? (
          <dl className="concept-details">
            <dt><T>Expression</T></dt>
            <dd className="expression">{conceptQuery.data.expression}</dd>
            <dt><T>Meaning in context</T></dt>
            <dd>
              {conceptQuery.data.contextual_meaning}
              <span className={`meaning-provenance ${conceptQuery.data.meaning_provenance}`}>
                {conceptQuery.data.meaning_provenance === "dictionary"
                  ? <T>From the dictionary</T>
                  : <T>AI explanation, not checked against a dictionary</T>}
              </span>
            </dd>
            {conceptQuery.data.dictionary_sense ? (
              <>
                <dt><T>Dictionary</T></dt>
                <dd className="dictionary-sense">
                  <span className="expression">{conceptQuery.data.dictionary_sense.headword}</span>
                  {conceptQuery.data.dictionary_sense.reading ? (
                    <span className="muted"> [{conceptQuery.data.dictionary_sense.reading}]</span>
                  ) : null}
                  {conceptQuery.data.dictionary_sense.part_of_speech ? (
                    <span className="muted"> ({conceptQuery.data.dictionary_sense.part_of_speech})</span>
                  ) : null}
                  <span className="dictionary-definition">{conceptQuery.data.dictionary_sense.definition}</span>
                  <small className="dictionary-credit muted">
                    <T>Source:</T>{" "}
                    <a href={conceptQuery.data.dictionary_sense.source_url} target="_blank" rel="noopener noreferrer">
                      {conceptQuery.data.dictionary_sense.source_name}
                    </a>
                    ,{" "}
                    <a href={conceptQuery.data.dictionary_sense.license_url} target="_blank" rel="noopener noreferrer">
                      {conceptQuery.data.dictionary_sense.license_name}
                    </a>
                  </small>
                </dd>
              </>
            ) : null}
            <dt><T>Source sentence</T></dt>
            <dd className="muted">{conceptQuery.data.source_segment_text}</dd>
            {conceptQuery.data.explanation ? (
              <>
                <dt><T>Explanation</T></dt>
                <dd>{conceptQuery.data.explanation}</dd>
              </>
            ) : null}
          </dl>
        ) : null}
        {conceptQuery.data ? (
          <WordActions save={{ source: "occurrence", library_item_id: libraryItemId, learning_object_id: learningObjectId, region_id: regionId }} />
        ) : null}
      </div>
    </div>
  );
}
