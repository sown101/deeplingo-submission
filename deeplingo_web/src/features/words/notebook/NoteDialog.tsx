import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { T, useT } from "../../../i18n/i18n";
import type { NotebookWord } from "./model";
import { NotebookDialog } from "./NotebookDialog";

// The learner's own note on a word. An empty note clears it.
export function NoteDialog({ word, onChanged, onClose }: { word: NotebookWord; onChanged: () => void; onClose: () => void }) {
  const t = useT();
  const { notebook } = useContainer();
  const [text, setText] = useState(word.note ?? "");
  const save = useMutation({
    mutationFn: () => notebook.setPersonal(word.conceptId, { note: text.trim() || null }),
    onSuccess: () => { onChanged(); onClose(); },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return <NotebookDialog title={word.note ? t("Edit note") : t("Add note")} size="tiny" closable={false} onClose={onClose}>
    <form className="nbp-form" onSubmit={submit}>
      <p className="nbp-form__word" lang={word.languageCode}>{word.text}</p>
      <textarea className="nb-input" autoFocus aria-label={t("Note")} placeholder={t("Write your note")} value={text} maxLength={1000}
                onChange={(event) => setText(event.target.value)} />
      {save.isError ? <p className="error" role="alert"><T>The note could not be saved. Please try again.</T></p> : null}
      <div className="nb-m-foot">
        <button type="button" className="nb-btn" onClick={onClose}><T>Cancel</T></button>
        <button type="submit" className="nb-btn main" disabled={save.isPending}>{word.note ? <T>Save</T> : <T>Add</T>}</button>
      </div>
    </form>
  </NotebookDialog>;
}
