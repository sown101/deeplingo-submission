import { useMutation } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { T, useT, tr } from "../../../i18n/i18n";
import { listErrorCode, type WaitingLine } from "../listsModels";
import { NotebookDialog } from "./NotebookDialog";

// Pasted lines the server could not settle alone: choose a meaning, or dismiss the line.
export function WaitingDialog({ listId, lines, onChanged, onClose }: { listId: string; lines: WaitingLine[]; onChanged: () => void; onClose: () => void }) {
  const t = useT();
  return <NotebookDialog title={t("Words that need a meaning")} size="narrow" onClose={onClose}>
    <ul className="nbp-waiting-list">
      {lines.map(line => <WaitingRow key={line.id} listId={listId} line={line} onChanged={onChanged} />)}
    </ul>
  </NotebookDialog>;
}

function WaitingRow({ listId, line, onChanged }: { listId: string; line: WaitingLine; onChanged: () => void }) {
  const t = useT();
  const { lists } = useContainer();
  const choose = useMutation({
    mutationFn: (pick: { entryId: string; senseId: string }) => lists.chooseMeaning(listId, line.id, pick.entryId, pick.senseId),
    onSuccess: onChanged,
  });
  const dismiss = useMutation({ mutationFn: () => lists.dismissLine(listId, line.id), onSuccess: onChanged });
  const busy = choose.isPending || dismiss.isPending;
  return <li className="nbp-waiting">
    <div className="nb-row-between">
      <strong>{line.text}</strong>
      <button type="button" className="nb-link" disabled={busy} aria-label={t("Dismiss {word}", { word: line.text })} onClick={() => dismiss.mutate()}>
        <T>Dismiss</T>
      </button>
    </div>
    {line.gloss ? <p className="small muted"><T gloss={line.gloss}>{"Your note: {gloss}"}</T></p> : null}
    {line.resolution === "unresolved" ? (
      <p className="small muted"><T>Not found in the dictionary. It was not added as a word.</T></p>
    ) : <>
      <p className="small muted"><T>Choose the meaning you want to learn:</T></p>
      <div className="nbp-waiting__choices">
        {line.candidates.map(candidate => (
          <button key={`${candidate.entryId}:${candidate.senseId}`} type="button" className="nbp-waiting__choice" disabled={busy}
                  aria-label={t("Use this meaning for {word}: {meaning}", { word: line.text, meaning: candidate.text })}
                  onClick={() => choose.mutate({ entryId: candidate.entryId, senseId: candidate.senseId })}>
            {candidate.partOfSpeech ? <span className="muted">({candidate.partOfSpeech}) </span> : null}
            {candidate.text}
          </button>
        ))}
      </div>
    </>}
    {choose.isError ? <p className="error small" role="alert">{chooseError(choose.error)}</p> : null}
    {dismiss.isError ? <p className="error small" role="alert"><T>That line could not be dismissed. Please try again.</T></p> : null}
  </li>;
}

function chooseError(error: unknown): string {
  if (listErrorCode(error) === "list_full") return tr("The notebook is full. Remove a word first.");
  return tr("That meaning could not be saved. Please try again.");
}
