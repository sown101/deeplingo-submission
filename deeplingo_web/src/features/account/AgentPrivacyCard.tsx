import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import type { AgentSignal, AgentSignalKind } from "../companion/companionModels";
import { T, useT } from "../../i18n/i18n";
import { ProfileRow, ProfileSwitch } from "./ProfileParts";

// The agent's one voice consent and what it has noted about the learner: closed labels only,
// never quotes or transcripts. The learner can look and delete at any time, even after revoking.
const KIND_LABEL: Record<AgentSignalKind, string> = {
  topic: "Interest",
  goal: "Goal",
  error_type: "Often mixed up",
  pace: "Speaking pace",
  turn_length: "Turn length",
};
const KEY = ["agent-privacy"];

function label(code: string) {
  const words = code.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function useAgentPrivacy() {
  const { companion } = useContainer();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const [consent, signals] = await Promise.all([companion.getAgentConsent(), companion.getAgentSignals()]);
      return { consent, signals };
    },
    retry: false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEY });
  const setConsent = useMutation({ mutationFn: (granted: boolean) => companion.setAgentConsent(granted), onSettled: refresh });
  const removeOne = useMutation({ mutationFn: (id: string) => companion.deleteAgentSignal(id), onSettled: refresh });
  const removeAll = useMutation({ mutationFn: () => companion.deleteAllAgentSignals(), onSettled: refresh });
  return { query, setConsent, removeOne, removeAll, busy: setConsent.isPending || removeOne.isPending || removeAll.isPending };
}

/** The voice consent as a switch, with its state in words and the full explanation one tap away. */
export function VoiceBox() {
  const t = useT();
  const { query, setConsent, removeOne, removeAll, busy } = useAgentPrivacy();
  const consent = query.data?.consent;
  return <div className="pf-box">
    <div className="pf-box__row">
      <span className="pf-box__label"><T>Voice processing</T></span>
      {consent ? <ProfileSwitch label={t("Voice processing")} on={consent.status === "granted"} disabled={busy}
        onChange={on => setConsent.mutate(on)} /> : null}
    </div>
    <p className="pf-hint"><T>Lets Tata listen and score your pronunciation. Audio is not stored.</T></p>
    {query.isPending ? <p className="pf-hint" role="status"><T>Loading agent settings…</T></p> : null}
    {query.isError ? <div role="alert" className="pf-alert"><p><T>Your agent settings could not be loaded.</T></p>
      <button type="button" className="pf-link-btn" onClick={() => void query.refetch()}><T>Retry agent settings</T></button>
    </div> : null}
    {setConsent.isError || removeOne.isError || removeAll.isError
      ? <p className="pf-error" role="alert"><T>That change could not be saved. Please try again.</T></p> : null}
    {consent ? <p className="pf-state">
      {consent.status === "ask" ? <T>You have not decided yet.</T>
        : consent.status === "granted" ? <T>Voice processing is on.</T> : <T>Voice processing is off.</T>}
      {consent.status === "ask" ? <> <button type="button" className="pf-link-btn" disabled={busy} onClick={() => setConsent.mutate(false)}><T>Not now</T></button></> : null}
    </p> : null}
    <details className="pf-details">
      <summary><T>Details</T></summary>
      <p><T>One setting for every conversation with the agent. It lets the agent process your speech briefly, including sending audio to a speech service to score pronunciation. Audio is not stored.</T></p>
    </details>
  </div>;
}

/** What the agent has noted, behind one row; each label can be deleted, or all of them. */
export function SignalsRow() {
  const t = useT();
  const { query, removeOne, removeAll, busy } = useAgentPrivacy();
  const signals = query.data?.signals;
  const summary = !signals ? "" : signals.length ? t("{n} notes", { n: signals.length }) : t("Tata has not noted anything yet");
  return <ProfileRow icon="✨" title={t("What Tata knows about you")} subtitle={summary} disabled={!signals}>
    {signals && signals.length === 0 ? <p className="pf-hint"><T>The agent has not noted anything about you yet.</T></p> : null}
    {signals && signals.length > 0 ? <>
      <ul className="signal-chips">
        {signals.map((signal: AgentSignal) => <li key={signal.id} className="dl-chip dl-chip--neutral">
          <span title={`${t(KIND_LABEL[signal.kind])} · ${signal.language_code}`}>{t(label(signal.code))}</span>
          <button type="button" className="dl-icon-btn" disabled={busy}
            aria-label={t("Delete signal: {name}", { name: t(label(signal.code)) })} onClick={() => removeOne.mutate(signal.id)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
          </button>
        </li>)}
      </ul>
      <div><button type="button" className="pf-link-btn danger" disabled={busy} onClick={() => removeAll.mutate()}><T>Delete all signals</T></button></div>
    </> : null}
  </ProfileRow>;
}
