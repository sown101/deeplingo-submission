import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { Icon } from "../../../design/notebookIcons";
import { T, useT, tr } from "../../../i18n/i18n";
import { listErrorCode, type ListSummary } from "../listsModels";
import { plain } from "./model";
import { NotebookDialog } from "./NotebookDialog";

// Choose a notebook in the same language, or create one here. The page does the moving.
export function MoveDialog({ title, languageCode, currentListId, busy, error, onDone, onClose }: {
  title: string;
  languageCode: string;
  currentListId: string | null;
  busy: boolean;
  error: string | null;
  onDone: (target: ListSummary) => void;
  onClose: () => void;
}) {
  const t = useT();
  const { lists } = useContainer();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<ListSummary | null>(null);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const shelf = useQuery({ queryKey: ["word-lists", "all"], queryFn: () => lists.list() });
  const create = useMutation({
    mutationFn: () => lists.create(languageCode, name.trim()),
    onSuccess: (created) => {
      setTarget(created);
      setNaming(false);
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["word-lists"] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate();
  }
  const wanted = plain(query.trim());
  const targets = (shelf.data ?? [])
    .filter(item => item.id !== currentListId && item.languageCode === languageCode)
    .filter(item => !wanted || plain(item.name).includes(wanted));

  return <NotebookDialog title={title} size="tiny" onClose={onClose}>
    <label className="nb-search nbp-search-tile">
      <Icon name="search" />
      <input type="search" aria-label={t("Search notebooks")} placeholder={t("Search")} value={query} onChange={(event) => setQuery(event.target.value)} />
    </label>
    {shelf.isLoading ? <p role="status" className="small muted"><T>Loading your notebooks…</T></p> : null}
    {shelf.isError ? <p role="alert" className="error small"><T>Your notebooks could not be loaded.</T></p> : null}
    <div className="nb-plist" role="group" aria-label={t("Choose a notebook")}>
      {targets.map(item => (
        <button key={item.id} type="button" className={target?.id === item.id ? "nb-pitem on" : "nb-pitem"} aria-pressed={target?.id === item.id} disabled={busy} onClick={() => setTarget(item)}>
          <span><strong>{item.name}</strong><small>{t("{n} words", { n: item.wordCount })}</small></span>
        </button>
      ))}
      {shelf.isSuccess && targets.length === 0 ? <p className="small muted"><T>No other notebook in this language yet.</T></p> : null}
    </div>
    {naming ? <form className="nbp-new" onSubmit={submit}>
      <input className="nb-input" type="text" autoFocus aria-label={t("Notebook name")} placeholder={t("Notebook name")} value={name} maxLength={60} onChange={(event) => setName(event.target.value)} />
      <button type="submit" className="nb-btn main" disabled={!name.trim() || create.isPending}><T>Create notebook</T></button>
    </form> : null}
    {create.isError ? <p role="alert" className="error small">{createError(create.error)}</p> : null}
    {error ? <p role="alert" className="error small">{error}</p> : null}
    <div className="nb-row-between">
      <button type="button" className="nb-chip-btn" aria-expanded={naming} onClick={() => setNaming(value => !value)}><Icon name="plus" /><T>New notebook</T></button>
      <button type="button" className="nb-btn main" disabled={!target || busy} onClick={() => { if (target) onDone(target); }}><T>Done</T></button>
    </div>
  </NotebookDialog>;
}

function createError(error: unknown): string {
  switch (listErrorCode(error)) {
    case "list_name_taken": return tr("You already have a notebook with that name.");
    case "too_many_lists": return tr("You have reached the limit of notebooks. Delete one first.");
    default: return tr("The notebook could not be created. Please try again.");
  }
}
