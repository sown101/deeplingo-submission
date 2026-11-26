import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useInRouterContext, useLocation } from "react-router-dom";
import { useContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import type { SaveWordRequest } from "./wordsApi";
import { aboveLevelNotice, type AboveLevelNotice } from "./wordsModels";
import { T, tr, useT } from "../../i18n/i18n";

// "Add to my words". Saving sends selectors only. A word above the
// learner's declared level asks for one confirmation before it is added (L1a).
// With `notebookLanguage`, the learner also picks notebooks of that language: All words is always
// included, and the saved word is then added to each chosen notebook.
export function WordActions({
  save,
  notebookLanguage,
}: {
  save: SaveWordRequest;
  notebookLanguage?: string;
}) {
  const t = useT();
  const inRouter = useInRouterContext();
  const { words, lists } = useContainer();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<AboveLevelNotice | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [notebookFailed, setNotebookFailed] = useState(false);
  const notebooks = useQuery({
    queryKey: ["word-lists", notebookLanguage],
    queryFn: () => lists.list(notebookLanguage),
    enabled: !!notebookLanguage,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: async (acknowledged: boolean) => {
      const word = await words.save(acknowledged ? { ...save, acknowledge_above_level: true } : save);
      setNotebookFailed(false);
      const added = await Promise.allSettled(chosen.map(listId => lists.addWord(listId, word.conceptId)));
      if (added.some(result => result.status === "rejected")) setNotebookFailed(true);
      return word;
    },
    onSuccess: () => {
      setNotice(null);
      void queryClient.invalidateQueries({ queryKey: ["word-lists"] });
      return queryClient.invalidateQueries({ queryKey: ["my-words"] });
    },
    onError: (error) => setNotice(aboveLevelNotice(error)),
  });
  const saved = mutation.data;
  const toggle = (listId: string) => setChosen(current => current.includes(listId) ? current.filter(id => id !== listId) : [...current, listId]);
  const addLabel = chosen.length ? t("Save to {n} places", { n: chosen.length + 1 }) : t("Add to my words");
  const videoPath = save.source !== "dictionary" ? `/library/videos/${save.library_item_id}/watch` : null;

  return (
    <div className="word-actions stack">
      {notebookLanguage && !saved ? <div className="save-places">
        <span className="save-places__title"><T>Save to</T></span>
        <div className="save-places__list" role="group" aria-label={t("Save to")}>
          <span className="save-place locked" aria-disabled="true">✓ <T>All words</T></span>
          {(notebooks.data ?? []).map(list => <button key={list.id} type="button" className="save-place" aria-pressed={chosen.includes(list.id)}
            disabled={mutation.isPending} onClick={() => toggle(list.id)}>{chosen.includes(list.id) ? "✓ " : ""}{list.name}</button>)}
          <NewNotebook language={notebookLanguage} disabled={mutation.isPending} onCreated={listId => setChosen(current => [...current, listId])} />
        </div>
      </div> : null}
      <div className="row">
        <button
          type="button"
          className="dl-btn dl-btn--secondary"
          onClick={() => mutation.mutate(false)}
          disabled={mutation.isPending || saved !== undefined}
        >
          {saved ? <T>Saved to my words</T> : mutation.isPending ? <T>Saving…</T> : addLabel}
        </button>
      </div>
      {saved && chosen.length && !notebookFailed ? <p className="small muted" role="status"><T n={chosen.length}>{"Also added to {n} notebooks."}</T></p> : null}
      {saved && notebookFailed ? <p className="error" role="alert"><T>Saved to my words, but not to every notebook. Add it from the notebook.</T></p> : null}
      {saved && videoPath && inRouter ? <SavedVideoLink to={videoPath} /> : null}
      {notice ? (
        <div role="alert" className="above-level-confirm stack">
          <p className="small">
            {notice.level ? <T level={notice.level}>{"This word is {level} level"}</T> : <T>This word is above level</T>}
            {notice.declaredLevel ? <T declared={notice.declaredLevel}>{", higher than the {declared} you set"}</T> : ""}<T>. It may be hard for now.</T>
          </p>
          <p className="row">
            <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={mutation.isPending}
                    onClick={() => mutation.mutate(true)}>
              <T>Add anyway</T>
            </button>
            <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => setNotice(null)}><T>Cancel</T></button>
          </p>
        </div>
      ) : null}
      {mutation.isError && !notice ? <p className="error" role="alert">{saveError(mutation.error)}</p> : null}
    </div>
  );
}

// A notebook made on the spot is chosen straight away.
function NewNotebook({ language, disabled, onCreated }: { language: string; disabled: boolean; onCreated: (listId: string) => void }) {
  const t = useT();
  const { lists } = useContainer();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (listName: string) => lists.create(language, listName),
    onSuccess: async created => {
      await queryClient.invalidateQueries({ queryKey: ["word-lists"] });
      onCreated(created.id);
      setOpen(false);
      setName("");
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate(name.trim());
  }
  if (!open) return <button type="button" className="save-place new" disabled={disabled} onClick={() => setOpen(true)}>+ <T>New notebook</T></button>;
  return <form className="save-place-form" onSubmit={submit}>
    <input autoFocus value={name} maxLength={60} aria-label={t("Notebook name")} placeholder={t("Notebook name")} onChange={event => setName(event.target.value)} />
    <button type="submit" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={!name.trim() || create.isPending}><T>Add</T></button>
    <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => setOpen(false)}><T>Cancel</T></button>
    {create.isError ? <p className="error small" role="alert"><T>The notebook could not be created. Please try again.</T></p> : null}
  </form>;
}

function SavedVideoLink({ to }: { to: string }) {
  const location = useLocation();
  return location.pathname === to ? null : <Link className="dl-btn dl-btn--secondary" to={to}><T>Watch this video</T></Link>;
}

function saveError(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) return tr("This word has no dictionary meaning to save yet.");
  return tr("This word could not be saved. Please try again.");
}
