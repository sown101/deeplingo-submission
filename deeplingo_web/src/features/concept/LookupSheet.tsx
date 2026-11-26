import { useQuery } from "@tanstack/react-query";
import { useModalDialog } from "../../lib/modalA11y";
import { useContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import type { TranscriptSegmentView } from "../../lib/api/dto";
import { WordActions } from "../words/WordActions";
import { T, useT, tr } from "../../i18n/i18n";
import { Icon } from "../../design/Icon";

// Meaning of any word or phrase the learner tapped or selected: the server derives the
// text from the segment, finds the longest dictionary unit containing the selection and
// says whether the selection is only part of it. "Add to my words" saves that sense.
export function LookupSheet({
  libraryItemId,
  segment,
  span,
  regionId,
  onClose,
}: {
  libraryItemId: string;
  segment: TranscriptSegmentView;
  span: { start: number; end: number };
  // The study part the word was looked up in: a word saved from here counts for that part's result.
  regionId?: string;
  onClose: () => void;
}) {
  const t = useT();
  const { playback, onboarding } = useContainer();
  const profile = useQuery({ queryKey: ["language-profile"], queryFn: () => onboarding.loadProfile(), retry: false });
  const dialogRef = useModalDialog(onClose);
  const lookupQuery = useQuery({
    queryKey: ["lookup", libraryItemId, segment.segment_id, span.start, span.end],
    queryFn: () => playback.lookup(libraryItemId, segment, span),
    retry: false,
    staleTime: Infinity,
  });
  const data = lookupQuery.data;
  const selected = [...segment.text].slice(span.start, span.end).join("");

  return (
    <div className="dialog-backdrop">
      <div
        ref={dialogRef}
        className="card dialog concept-sheet lookup-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="lookup-sheet-title"
        tabIndex={-1}
      >
        <div className="row between">
          <div className="lookup-head">
            <h2 id="lookup-sheet-title" className="title-2">{data ? data.unit_text : selected}</h2>
            {data && data.selection_is_part ? <small>{data.unit_kind === "phrase" ? t("phrase") : t("word")} · {t("you chose “{selected}”", { selected })}</small> : null}
          </div>
          <button type="button" className="dl-icon-btn" onClick={onClose} aria-label={t("Close")} title={t("Close")}>
            <Icon name="close" />
          </button>
        </div>

        {lookupQuery.isLoading ? <p role="status"><T selected={selected}>{"Looking up “{selected}”…"}</T></p> : null}

        {lookupQuery.isError ? (
          <div>
            <p className="error" role="alert">{lookupError(lookupQuery.error)}</p>
            <button type="button" className="dl-btn dl-btn--secondary" onClick={() => lookupQuery.refetch()}>
              <T>Retry</T>
            </button>
          </div>
        ) : null}

        {data ? (
          <>
            {data.context_before || data.context_after ? (
              <p className="lookup-context" aria-label={t("In context")}>
                {data.context_before ? <>{data.context_before} </> : null}
                {[...segment.text].slice(0, data.unit_start).join("")}<b>{data.unit_text}</b>{[...segment.text].slice(data.unit_end).join("")}
                {data.context_after ? <> {data.context_after}</> : null}
              </p>
            ) : null}
            {data.selection_is_part ? (
              <p className="lookup-part" role="note">
                “{[...segment.text].slice(data.selection_start, data.selection_end).join("")}<T>” is part of the</T>{" "}
                {data.unit_kind === "phrase" ? <T>phrase</T> : <T>word</T>} <strong>{data.unit_text}</strong>
                {data.headword && data.headword !== data.unit_text ? <> ({data.headword})</> : null}.
              </p>
            ) : null}
            <dl className="concept-details">
              {data.meaning ? (
                <>
                  <dt><T>Meaning here</T></dt>
                  <dd>
                    {data.meaning}
                    <span className={`meaning-provenance ${data.meaning_provenance === "translated_from_sense" ? "dictionary" : "unverified"}`}>
                      {data.meaning_provenance === "translated_from_sense"
                        ? <T>From the dictionary</T>
                        : <T>AI explanation, not checked against a dictionary</T>}
                    </span>
                  </dd>
                </>
              ) : null}
              {data.pattern.length ? (
                <>
                  <dt><T>Structure</T></dt>
                  <dd>
                    <span className="lookup-pattern">
                      {data.pattern.map((part, index) => <span key={index}>{index ? <em aria-hidden="true">+</em> : null}<span className="lookup-pattern__part">{part}</span></span>)}
                    </span>
                    {data.pattern_explanation ? <span className="lookup-pattern__text">{data.pattern_explanation}</span> : null}
                  </dd>
                </>
              ) : null}
              {data.note ? (
                <>
                  <dt><T>How it is used</T></dt>
                  <dd>{data.note}</dd>
                </>
              ) : null}
              {data.examples.length ? (
                <>
                  <dt><T>Examples</T></dt>
                  <dd className="lookup-examples">
                    {data.examples.map(example => <span key={example.text}><span>{example.text}</span><small>{example.translation}</small></span>)}
                  </dd>
                </>
              ) : null}
              {data.dictionary_gloss && data.source ? (
                <>
                  <dt><T>Dictionary</T></dt>
                  <dd className="dictionary-sense">
                    {/* The title already shows the unit; repeat the headword only when it differs (went → go). */}
                    {data.headword && data.headword !== data.unit_text ? <span className="expression">{data.headword}</span> : null}
                    {data.reading ? <span className="muted"> [{data.reading}]</span> : null}
                    {data.part_of_speech ? <span className="muted"> ({data.part_of_speech})</span> : null}
                    {data.level ? <span className="level-badge"> {data.level}</span> : null}
                    <span className="dictionary-definition">{data.dictionary_gloss}</span>
                    <small className="dictionary-credit muted">
                      <T>Source:</T>{" "}
                      <a href={data.source.entry_url} target="_blank" rel="noopener noreferrer">{data.source.name}</a>,{" "}
                      <a href={data.source.license_url} target="_blank" rel="noopener noreferrer">{data.source.license_name}</a>
                    </small>
                  </dd>
                </>
              ) : null}
              {data.meaning_provenance === "unavailable" ? (
                <dd className="muted"><T>No meaning is available for this right now.</T></dd>
              ) : null}
            </dl>
            {data.headword ? (
              <WordActions
                notebookLanguage={profile.data?.learning_language ?? undefined}
                save={{
                  source: "lookup",
                  library_item_id: libraryItemId,
                  segment_id: segment.segment_id,
                  start_codepoint: data.selection_start,
                  end_codepoint: data.selection_end,
                  sense_id: data.sense_id,
                  region_id: regionId,
                }}
              />
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

function lookupError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) return tr("Too many lookups. Please wait a moment.");
  if (error instanceof ApiError && error.status === 422) return tr("Select a word in this sentence.");
  return tr("This word could not be looked up. Please try again.");
}
