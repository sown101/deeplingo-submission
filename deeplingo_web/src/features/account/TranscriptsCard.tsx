import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import type { KeptTranscript } from "../companion/companionModels";
import { TRANSCRIPT_CONSENT_KEY } from "../companion/TranscriptConsentPrompt";
import { T, useT } from "../../i18n/i18n";
import { ProfileRow, ProfileSwitch } from "./ProfileParts";

const LIST_KEY = ["kept-transcripts"];
const WEAK_ACCURACY = 60;

// FR-3.11: the separate consent to keep spoken turns as text, and those turns. The learner can look and delete
// at any time, whatever the consent says. Nothing here is cached by the browser (the server sends no-store).
function useTranscripts() {
  const { companion } = useContainer();
  const queryClient = useQueryClient();
  const consent = useQuery({ queryKey: TRANSCRIPT_CONSENT_KEY, queryFn: () => companion.getTranscriptConsent(), retry: false });
  const list = useInfiniteQuery({
    queryKey: LIST_KEY,
    queryFn: ({ pageParam }) => companion.getTranscripts(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_before,
    retry: false,
  });
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: TRANSCRIPT_CONSENT_KEY }),
    queryClient.invalidateQueries({ queryKey: LIST_KEY }),
  ]);
  const setConsent = useMutation({ mutationFn: (granted: boolean) => companion.setTranscriptConsent(granted), onSettled: refresh });
  const removeOne = useMutation({ mutationFn: (id: string) => companion.deleteTranscript(id), onSettled: refresh });
  const removeAll = useMutation({ mutationFn: () => companion.deleteAllTranscripts(), onSettled: refresh });
  const turns = list.data?.pages.flatMap(page => page.transcripts) ?? [];
  return { consent, list, refresh, setConsent, removeOne, removeAll, turns,
    busy: setConsent.isPending || removeOne.isPending || removeAll.isPending };
}

/** The transcript consent as a switch, separate from voice processing. */
export function TranscriptBox() {
  const t = useT();
  const { consent, list, refresh, setConsent, removeOne, removeAll, busy } = useTranscripts();
  const state = consent.data;
  return <div className="pf-box">
    <div className="pf-box__row">
      <span className="pf-box__label"><T>Keep transcripts</T></span>
      {state ? <ProfileSwitch label={t("Keep transcripts")} on={state.status === "granted"} disabled={busy}
        onChange={on => setConsent.mutate(on)} /> : null}
    </div>
    <p className="pf-hint"><T>Keeps the text for 12 months so you can review mistakes. Audio is not kept.</T></p>
    {consent.isError || list.isError ? <div role="alert" className="pf-alert"><p><T>Your transcripts could not be loaded.</T></p>
      <button type="button" className="pf-link-btn" onClick={() => void refresh()}><T>Retry transcripts</T></button>
    </div> : null}
    {setConsent.isError || removeOne.isError || removeAll.isError
      ? <p className="pf-error" role="alert"><T>That change could not be saved. Please try again.</T></p> : null}
    {state ? <p className="pf-state">{state.status === "granted"
      ? (state.active ? <T>Transcripts are being kept.</T> : <T>Transcripts are allowed but not kept while voice processing is off.</T>)
      : state.status === "revoked" ? <T>Transcripts are not kept.</T> : <T>Transcripts are off until you allow them.</T>}</p> : null}
    <details className="pf-details">
      <summary><T>Details</T></summary>
      <p><T>With your permission, the text of what you say to the agent is kept for 12 months to calibrate your speaking level, to let you review your mistakes and to let the agent remember your recent turns. No audio is kept. It needs voice processing to be on as well.</T></p>
    </details>
  </div>;
}

/** The kept turns behind one row: each can be deleted, or all of them, and older ones load on request. */
export function TranscriptsRow() {
  const t = useT();
  const { list, removeOne, removeAll, turns, busy } = useTranscripts();
  const when = new Intl.DateTimeFormat(t("en-US"), { dateStyle: "medium", timeStyle: "short" });
  const summary = !list.isSuccess ? "" : turns.length ? t("{n} turns kept", { n: turns.length }) : t("No transcripts are kept.");
  return <ProfileRow icon="🗒" title={t("Kept transcripts")} subtitle={summary} disabled={!list.isSuccess}>
    {turns.length === 0 ? <p className="pf-hint"><T>No transcripts are kept.</T></p> : <>
      <ul className="transcript-list">
        {turns.map((turn: KeptTranscript) => <TranscriptItem key={turn.id} turn={turn} when={when.format(new Date(turn.occurred_at))}
          busy={busy} onDelete={() => removeOne.mutate(turn.id)} />)}
      </ul>
      <div className="pf-row__actions">
        {list.hasNextPage ? <button type="button" className="pf-link-btn" disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}><T>Show older transcripts</T></button> : null}
        <button type="button" className="pf-link-btn danger" disabled={busy} onClick={() => removeAll.mutate()}><T>Delete all transcripts</T></button>
      </div>
    </>}
  </ProfileRow>;
}

function TranscriptItem({ turn, when, busy, onDelete }: { turn: KeptTranscript; when: string; busy: boolean; onDelete: () => void }) {
  const t = useT();
  const weak = turn.word_scores.filter(score => score.error_type === "mispronunciation" || score.accuracy < WEAK_ACCURACY);
  return (
    <li className="transcript-item stack tight">
      <div className="row between">
        <span className="small muted">{when}{turn.topic ? ` · ${turn.topic}` : ""}</span>
        <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={busy} aria-label={t("Delete transcript from {when}", { when })} onClick={onDelete}><T>Delete</T></button>
      </div>
      {turn.agent_text ? <p className="small muted">{turn.agent_text}</p> : null}
      <p lang={turn.language_code}>{turn.learner_text}</p>
      {turn.grammar_errors.map((error, index) => <p key={index} className="small">
        <span lang={turn.language_code}>{error.quote}</span> → <strong lang={turn.language_code}>{error.suggestion}</strong>
        {error.note ? <span className="muted"> · {error.note}</span> : null}
      </p>)}
      {weak.length > 0 ? <p className="small muted"><T>Words to practise:</T> <span lang={turn.language_code}>{weak.map(score => score.word).join(", ")}</span></p> : null}
    </li>
  );
}
