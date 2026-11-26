import { useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { Icon } from "../../design/notebookIcons";
import { Mascot } from "../../design/Mascot";
import { T, useT } from "../../i18n/i18n";
import { ApiError } from "../../lib/api/errors";
import { MAX_BATCH_LINES, type ImportReport } from "./listsModels";
import type { WordSetDetail, WordSetWord } from "./notebookApi";
import { createNotebookError, ShelfDialog } from "./WordListsScreen";
import "./notebook-base.css";
import "./shelf.css";

const PAGE_SIZE = 50;

interface AddResult { report: ImportReport; notebookName: string }

// A ready-made set: read it page by page and copy the words you pick into a notebook.
export function WordSetScreen() {
  const t = useT();
  const { setKey = "" } = useParams();
  const { notebook } = useContainer();
  const [offset, setOffset] = useState(0);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState<AddResult | null>(null);
  const top = useRef<HTMLDivElement>(null);
  const setQuery = useQuery({
    queryKey: ["word-set", setKey, offset],
    queryFn: () => notebook.set(setKey, offset),
    placeholderData: keepPreviousData,
  });

  function goTo(next: number) {
    setOffset(next);
    setSelected(new Set());
    top.current?.scrollIntoView?.();
  }

  function stopSelecting() {
    setSelecting(false);
    setSelected(new Set());
  }

  function toggle(entryId: string) {
    setSelected(current => {
      const next = new Set(current);
      if (!next.delete(entryId)) next.add(entryId);
      return next;
    });
  }

  const back = <Link className="shelf-back" to="/words/lists"><Icon name="back" /><T>Back</T></Link>;

  if (setQuery.isLoading) return <section className="shelf-page">
    <div className="shelf-set-head">{back}<div className="dl-skel shelf-skel-title" aria-hidden="true" /></div>
    <div className="shelf-words" role="status">
      <span className="sr-only"><T>Loading this set…</T></span>
      <div className="dl-skel shelf-skel-card" aria-hidden="true" />
      <div className="dl-skel shelf-skel-card" aria-hidden="true" />
      <div className="dl-skel shelf-skel-card" aria-hidden="true" />
      <div className="dl-skel shelf-skel-card" aria-hidden="true" />
    </div>
  </section>;
  if (setQuery.isError || !setQuery.data) {
    const missing = setQuery.error instanceof ApiError && setQuery.error.status === 404;
    return <section className="shelf-page">
      <div className="shelf-set-head">{back}</div>
      <div className="shelf-card" role="alert">
        {missing ? <p className="error"><T>This set was not found.</T></p> : <>
          <p className="error"><T>This set could not be loaded.</T></p>
          <button type="button" className="nb-btn" onClick={() => void setQuery.refetch()}><T>Retry</T></button>
        </>}
      </div>
    </section>;
  }

  const set = setQuery.data;
  const entryIds = [...new Set(set.words.map(word => word.entryId))];
  const allSelected = entryIds.length > 0 && entryIds.every(id => selected.has(id));
  const hasPrevious = set.offset > 0;
  const hasNext = set.offset + set.words.length < set.wordCount;

  return <section className="shelf-page">
    <div ref={top} className="shelf-set-head">
      {back}
      <h1 className="shelf-set-name">{set.name}</h1>
      <div className="shelf-set-meta"><Icon name="book" />{t("{n} words", { n: set.wordCount })}</div>
    </div>

    {result ? <AddSummary result={result} /> : null}

    <section className="shelf-card">
      <div className="shelf-list-bar">
        {selecting ? <>
          <button type="button" className="nb-chip-btn" aria-pressed={allSelected} onClick={() => setSelected(allSelected ? new Set() : new Set(entryIds))}>
            <span className={`shelf-pick shelf-pick--small${allSelected ? " on" : ""}`} aria-hidden="true"><Icon name="check" /></span><T>Select all</T>
          </button>
          <button type="button" className="nb-chip-btn shelf-push" onClick={stopSelecting}><Icon name="close" /><T>Cancel</T></button>
        </> : <button type="button" className="nb-chip-btn" onClick={() => { setResult(null); setSelecting(true); }}><Icon name="check" /><T>Select</T></button>}
      </div>

      {set.words.length ? (
        <ul className="shelf-words">
          {set.words.map(word => (
            <li key={`${word.entryId}:${word.senseId}`}>
              {selecting ? (
                <button type="button" className={`shelf-word${selected.has(word.entryId) ? " on" : ""}`} aria-pressed={selected.has(word.entryId)} onClick={() => toggle(word.entryId)}>
                  <span className="shelf-pick" aria-hidden="true"><Icon name="check" /></span>
                  <WordBody word={word} language={set.languageCode} />
                </button>
              ) : <div className="shelf-word"><WordBody word={word} language={set.languageCode} /></div>}
            </li>
          ))}
        </ul>
      ) : <div className="shelf-empty"><Mascot state="listen" /><p><T>This set has no words yet.</T></p></div>}

      {hasPrevious || hasNext ? (
        <nav className="shelf-pager" aria-label={t("Pages")}>
          <button type="button" className="nb-btn" disabled={!hasPrevious || setQuery.isPlaceholderData} onClick={() => goTo(Math.max(0, offset - PAGE_SIZE))}><T>Previous</T></button>
          <span>{t("{from}–{to} of {total}", { from: set.offset + 1, to: set.offset + set.words.length, total: set.wordCount })}</span>
          <button type="button" className="nb-btn" disabled={!hasNext || setQuery.isPlaceholderData} onClick={() => goTo(offset + PAGE_SIZE)}><T>Next</T></button>
        </nav>
      ) : null}
    </section>

    {selecting ? <div className="shelf-floatbar">
      <button type="button" disabled={selected.size === 0} onClick={() => setAdding(true)}><Icon name="plus" /><T>Add to notebook</T></button>
    </div> : null}

    {adding ? <AddToNotebookDialog set={set} entryIds={[...selected].slice(0, MAX_BATCH_LINES)} onClose={() => setAdding(false)}
      onDone={added => { setAdding(false); setResult(added); stopSelecting(); }} /> : null}
  </section>;
}

function WordBody({ word, language }: { word: WordSetWord; language: string }) {
  return <span className="shelf-word__body">
    <span className="shelf-term" lang={language}>
      {word.text}{word.traditional && word.traditional !== word.text ? <small>【{word.traditional}】</small> : null}
    </span>
    {word.reading ? <span className="shelf-reading">{word.reading}</span> : null}
    {/* Dictionary text, kept as it comes. */}
    <span className="shelf-meaning" lang="en">{word.meaning}</span>
  </span>;
}

function AddSummary({ result }: { result: AddResult }) {
  const t = useT();
  const { report, notebookName } = result;
  const parts: string[] = [];
  if (report.matched) parts.push(t("{n} added to “{name}”", { n: report.matched, name: notebookName }));
  if (report.alreadyInList) parts.push(t("{n} already in the notebook", { n: report.alreadyInList }));
  if (report.unresolved) parts.push(t("{n} not found in the dictionary", { n: report.unresolved }));
  if (report.aboveLevel) parts.push(t("{n} above your level", { n: report.aboveLevel }));
  return <div className="shelf-card shelf-report" role="status">
    <p>{parts.length ? parts.join(" · ") : <T>Nothing new to add.</T>}</p>
    {report.listFull ? <p className="error" role="alert"><T>The notebook is full. Remove a word to add more.</T></p> : null}
  </div>;
}

function AddToNotebookDialog({ set, entryIds, onClose, onDone }: {
  set: WordSetDetail; entryIds: string[]; onClose: () => void; onDone: (result: AddResult) => void;
}) {
  const t = useT();
  const { lists, notebook } = useContainer();
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<{ id: string; name: string } | null>(null);
  const [filter, setFilter] = useState("");
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const listsQuery = useQuery({ queryKey: ["word-lists", set.languageCode], queryFn: () => lists.list(set.languageCode) });

  const create = useMutation({
    mutationFn: (listName: string) => lists.create(set.languageCode, listName),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["word-lists"] });
      setTarget({ id: created.id, name: created.name });
      setNaming(false);
      setName("");
    },
  });
  const add = useMutation({
    mutationFn: (listId: string) => notebook.addFromSet(listId, entryIds),
    onSuccess: (report) => {
      void queryClient.invalidateQueries({ queryKey: ["word-lists"] });
      void queryClient.invalidateQueries({ queryKey: ["my-words"] });
      if (target) onDone({ report, notebookName: target.name });
    },
  });

  function submitName(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed) create.mutate(trimmed);
  }

  const needle = filter.trim().toLowerCase();
  const shown = (listsQuery.data ?? []).filter(list => list.name.toLowerCase().includes(needle));

  return <ShelfDialog title={t("Add to notebook")} closeButton onClose={onClose}>
    <label className="nb-search shelf-search">
      <Icon name="search" />
      <input className="shelf-search__input" type="search" placeholder={t("Search")} aria-label={t("Search notebooks")} value={filter} onChange={event => setFilter(event.target.value)} />
    </label>
    <div className="nb-plist">
      {listsQuery.isLoading ? <p role="status"><T>Loading your notebooks…</T></p> : null}
      {listsQuery.isError ? <p className="error" role="alert"><T>Your notebooks could not be loaded.</T></p> : null}
      {shown.map(list => (
        <button key={list.id} type="button" className={`nb-pitem${target?.id === list.id ? " on" : ""}`} aria-pressed={target?.id === list.id} onClick={() => setTarget({ id: list.id, name: list.name })}>
          <span><strong>{list.name}</strong><small>{t("{n} words", { n: list.wordCount })}</small></span>
        </button>
      ))}
      {listsQuery.isSuccess && listsQuery.data.length === 0 ? <p className="shelf-muted"><T>No notebooks in this language yet.</T></p> : null}
    </div>
    {create.isError ? <p className="error" role="alert">{createNotebookError(create.error)}</p> : null}
    {add.isError ? <p className="error" role="alert"><T>The words could not be added. Please try again.</T></p> : null}
    {naming ? (
      <form className="shelf-inline-form" onSubmit={submitName}>
        <input className="shelf-input" type="text" autoFocus aria-label={t("Notebook name")} placeholder={t("Enter your notebook name")} value={name} maxLength={60} onChange={event => setName(event.target.value)} />
        <button type="button" className="nb-btn" onClick={() => setNaming(false)}><T>Cancel</T></button>
        <button type="submit" className="nb-btn main" disabled={!name.trim() || create.isPending}><T>Add</T></button>
      </form>
    ) : (
      <div className="nb-row-between">
        <button type="button" className="nb-chip-btn" onClick={() => setNaming(true)}><Icon name="plus" /><T>Create notebook</T></button>
        <button type="button" className="nb-btn main" disabled={!target || add.isPending} onClick={() => { if (target) add.mutate(target.id); }}><T>Done</T></button>
      </div>
    )}
  </ShelfDialog>;
}
