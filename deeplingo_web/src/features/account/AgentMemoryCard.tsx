import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import type { AgentMemoryItem, AgentMemoryKind } from "../companion/companionModels";
import { T, useT } from "../../i18n/i18n";
import { ProfileRow } from "./ProfileParts";

const KEY = ["agent-memory"];
const KIND_LABEL: Record<AgentMemoryKind, string> = {
  goal: "Goal",
  interest: "Interest",
  error: "Recurring mistake",
  follow_up: "Next time",
};

/** The short notes the agent keeps across conversations: the learner can read each one and delete it, or all of them. */
export function AgentMemoryRow() {
  const t = useT();
  const { companion } = useContainer();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const list = useQuery({ queryKey: KEY, queryFn: () => companion.getAgentMemory(), retry: false });
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEY });
  const removeOne = useMutation({ mutationFn: (id: string) => companion.deleteAgentMemoryItem(id), onSettled: refresh });
  const removeAll = useMutation({ mutationFn: () => companion.deleteAllAgentMemory(), onSettled: refresh, onSuccess: () => setConfirming(false) });
  const busy = removeOne.isPending || removeAll.isPending;
  const notes = list.data;
  const summary = !notes ? "" : notes.length ? t("{n} notes", { n: notes.length }) : t("Tata has not noted anything yet");
  return <ProfileRow icon="🧠" title={t("What Tata remembers about you")} subtitle={summary}>
    <p className="pf-hint"><T>These are short notes from your conversations. Delete one and Tata forgets it.</T></p>
    {list.isPending ? <p className="pf-hint" role="status"><T>Loading what Tata remembers…</T></p> : null}
    {list.isError ? <div role="alert" className="pf-alert"><p><T>What Tata remembers could not be loaded.</T></p>
      <button type="button" className="pf-link-btn" onClick={() => void list.refetch()}><T>Retry what Tata remembers</T></button>
    </div> : null}
    {removeOne.isError || removeAll.isError
      ? <p className="pf-error" role="alert"><T>That change could not be saved. Please try again.</T></p> : null}
    {notes && notes.length === 0 ? <p className="pf-hint"><T>Tata has not noted anything yet.</T></p> : null}
    {notes && notes.length > 0 ? <>
      <ul className="transcript-list">
        {notes.map((note: AgentMemoryItem) => <li key={note.id} className="transcript-item stack tight">
          <div className="row between">
            <span className="small muted">{t(KIND_LABEL[note.kind])}</span>
            <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={busy}
              aria-label={t("Delete note: {text}", { text: note.text })} onClick={() => removeOne.mutate(note.id)}><T>Delete</T></button>
          </div>
          <p lang={note.language_code ?? undefined}>{note.text}</p>
        </li>)}
      </ul>
      {confirming ? <div role="alertdialog" aria-label={t("Delete all notes?")} className="stack tight">
        <p className="pf-hint"><T>Tata will forget all of these notes. This cannot be undone.</T></p>
        <div className="pf-row__actions">
          <button type="button" className="pf-link-btn danger" disabled={busy} onClick={() => removeAll.mutate()}><T>Yes, delete all</T></button>
          <button type="button" className="pf-link-btn" disabled={busy} onClick={() => setConfirming(false)}><T>Cancel</T></button>
        </div>
      </div> : <div><button type="button" className="pf-link-btn danger" disabled={busy} onClick={() => setConfirming(true)}><T>Delete all</T></button></div>}
    </> : null}
  </ProfileRow>;
}
