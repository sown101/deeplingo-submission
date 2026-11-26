import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { Icon } from "../../design/notebookIcons";
import { Mascot } from "../../design/Mascot";
import { T, useT, tr } from "../../i18n/i18n";
import { useModalDialog } from "../../lib/modalA11y";
import { dueWords } from "../home/HomeEvidence";
import { ReviewSetupSheet } from "../notebookStudy/ReviewSetupSheet";
import type { StudyWord } from "../notebookStudy/studyTypes";
import { ReviewDecks } from "../review/ReviewDecks";
import { listErrorCode, type ListSummary } from "./listsModels";
import type { WordSet } from "./notebookApi";
import type { MyWord } from "./wordsModels";
import "./notebook-base.css";
import "./shelf.css";
import { GrammarShelf } from "./GrammarShelf";

type SortOrder = "new" | "old" | "az" | "za";

// A language's own name is the same in every interface language; the second half follows the interface.
const LANGUAGE_NAMES: Record<string, string> = { en: "English", zh: "中文" };
const LANGUAGE_LABELS: Record<string, string> = { en: "English", zh: "Chinese" };

const LEVELS = [{ label: "New" }, { label: "Recognised" }, { label: "Recalled" }, { label: "With a hint" }, { label: "On my own" }];

// The shelf: what to study today on the left, every notebook on the right. A notebook only groups
// words; deleting one never removes a word from All words.
export function WordListsScreen() {
  const t = useT();
  const { lists, onboarding, words } = useContainer();
  // `?tab=grammar` opens the Grammar tab, for links from Tata and from the old grammar page.
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab");
  const [tab, setTab] = useState<"notebooks" | "grammar">(tabParam === "grammar" ? "grammar" : "notebooks");
  // A link that changes only the query (Tata's cards) reaches this screen without remounting it.
  useEffect(() => { setTab(tabParam === "grammar" ? "grammar" : "notebooks"); }, [tabParam]);
  function selectTab(next: "notebooks" | "grammar") {
    setTab(next);
    if (next === "notebooks" && tabParam) {
      const updated = new URLSearchParams(params);
      updated.delete("tab");
      setParams(updated, { replace: true });
    }
  }
  const profileQuery = useQuery({ queryKey: ["language-profile"], queryFn: () => onboarding.loadProfile() });
  const language = profileQuery.data?.learning_language ?? null;
  const listsQuery = useQuery({
    // Every language together, each notebook labelled (owner decision 2026-11-08).
    queryKey: ["word-lists", "all"],
    queryFn: () => lists.list(),
    enabled: profileQuery.isSuccess,
  });
  // Its failure never hides the notebooks.
  const wordsQuery = useQuery({
    queryKey: ["my-words", language],
    queryFn: () => words.list(language ?? undefined),
    enabled: language !== null,
    retry: false,
  });

  const toggle = <div className="nb-toggle" role="group" aria-label={t("Notebook area")}>
    <button type="button" className={tab === "notebooks" ? "on" : ""} aria-pressed={tab === "notebooks"} onClick={() => selectTab("notebooks")}><T>Notebooks</T></button>
    <button type="button" className={tab === "grammar" ? "on" : ""} aria-pressed={tab === "grammar"} onClick={() => selectTab("grammar")}><T>Grammar</T></button>
  </div>;

  return (
    <section className="shelf-page">
      <h1 className="sr-only"><T>Notebooks</T></h1>
      {tab === "grammar" ? <GrammarShelf toggle={toggle} language={language} /> : (
        <div className="shelf-grid">
          <div className="shelf-col">
            {toggle}
            <WordChart words={wordsQuery.data?.words ?? null} language={language} failed={wordsQuery.isError} onRetry={() => void wordsQuery.refetch()} />
            <ReviewDecks />
            <Link className="shelf-banner" to="/agent?mode=voice&entry=home">
              <Mascot state="listen" />
              <strong><T>Practise with Tata</T></strong>
              <span className="shelf-banner__go"><T>Start speaking</T> ›</span>
            </Link>
            <Link className="shelf-promo" to="/home">
              <span className="shelf-promo__art" aria-hidden="true"><Icon name="play" /></span>
              <span className="shelf-promo__text">
                <strong><T>Words from videos</T></strong>
                <small><T>Go back to the words you saved while watching videos</T></small>
              </span>
              <Icon name="chevron" />
            </Link>
          </div>
          <Shelf
            language={language}
            lists={listsQuery.data ?? null}
            loading={listsQuery.isLoading || profileQuery.isLoading}
            failed={listsQuery.isError || profileQuery.isError}
            onRetry={() => void (profileQuery.isError ? profileQuery.refetch() : listsQuery.refetch())}
          />
        </div>
      )}
    </section>
  );
}

function toStudyWord(word: MyWord): StudyWord {
  return {
    conceptId: word.conceptId, languageCode: word.languageCode, text: word.text, traditional: word.traditional,
    reading: word.reading, gloss: word.gloss, note: word.note, favorite: word.favorite,
  };
}

function statusCounts(words: MyWord[]) {
  const count = (test: (word: MyWord) => boolean) => words.filter(test).length;
  return [
    { label: "Learning", tone: "learning", n: count(w => w.saved && w.status === "active" && w.rung < 3) },
    { label: "Can use", tone: "can-use", n: count(w => w.saved && w.status === "active" && w.rung >= 3) },
    { label: "Paused", tone: "paused", n: count(w => w.saved && w.status === "suspended") },
  ];
}

// How the slices of the status ring fill the circle, each colour from a token in shelf.css.
function ringBackground(parts: { tone: string; n: number }[], total: number): string | undefined {
  if (total === 0) return undefined;
  let start = 0;
  const stops = parts.map(part => {
    const end = start + (part.n / total) * 360;
    const stop = `var(--shelf-${part.tone}) ${start}deg ${end}deg`;
    start = end;
    return stop;
  });
  return `conic-gradient(${stops.join(",")})`;
}

function WordChart({ words, language, failed, onRetry }: { words: MyWord[] | null; language: string | null; failed: boolean; onRetry: () => void }) {
  const t = useT();
  const navigate = useNavigate();
  const [view, setView] = useState<"bar" | "donut">("bar");
  const [reviewing, setReviewing] = useState(false);

  if (failed) {
    return <section className="shelf-card" role="alert">
      <p className="error"><T>Your words could not be loaded.</T></p>
      <button type="button" className="nb-btn" onClick={onRetry}><T>Retry</T></button>
    </section>;
  }
  if (!words) return <div className="shelf-card" aria-hidden="true"><div className="dl-skel shelf-chart-loading" /></div>;

  const saved = words.filter(word => word.saved);
  const levels = LEVELS.map((level, index) => ({ ...level, n: saved.filter(word => Math.min(word.rung, 4) === index).length }));
  const tallest = Math.max(1, ...levels.map(level => level.n));
  const statuses = statusCounts(words);
  const statusTotal = statuses.reduce((sum, part) => sum + part.n, 0);
  const due = dueWords(words, new Date());

  return <section className="shelf-card">
    <div className="shelf-chart-head">
      <h2 className="shelf-chart-title">{view === "bar" ? <><T>Memory</T> <em><T>by level</T></em></> : <T>Vocabulary chart</T>}</h2>
      <span className="nb-viewtog shelf-viewtog">
        <button type="button" aria-pressed={view === "bar"} aria-label={t("Bar chart")} onClick={() => setView("bar")}><Icon name="chart" /></button>
        <button type="button" aria-pressed={view === "donut"} aria-label={t("Donut chart")} onClick={() => setView("donut")}><Icon name="donut" /></button>
      </span>
    </div>
    {view === "bar" ? <>
      <div className="shelf-bars">
        {levels.map((level, index) => (
          <button key={level.label} type="button" className="shelf-bar" data-level={index}
                  aria-label={t("See {n} words at level {level}", { n: level.n, level: t(level.label) })}
                  onClick={() => navigate(`/words?level=${index}`)}>
            <span>{level.n}</span>
            <i style={{ "--shelf-h": level.n / tallest } as React.CSSProperties} />
          </button>
        ))}
      </div>
      <div className="shelf-bar-labels" aria-hidden="true">{levels.map(level => <span key={level.label}>{t(level.label)}</span>)}</div>
    </> : (
      <div className="shelf-donut">
        <div className="shelf-ring" style={{ background: ringBackground(statuses, statusTotal) }}>
          <div>{statusTotal}<small><T>words</T></small></div>
        </div>
        <div className="shelf-legend">
          {statuses.map(part => <div key={part.label}><b data-tone={part.tone}>{part.n}</b>{t(part.label)}</div>)}
        </div>
      </div>
    )}
    <button type="button" className="shelf-due" disabled={due.length === 0 || !language} onClick={() => setReviewing(true)}>
      <T>Review now</T>{" "}<b>{due.length}</b>{" "}<T>words</T>
      <Mascot state="happy" />
    </button>
    {reviewing ? <ReviewSetupSheet scope="all" words={due.map(toStudyWord)} preselected={due.map(word => word.conceptId)} onClose={() => setReviewing(false)} /> : null}
  </section>;
}

function sortNotebooks(lists: ListSummary[], order: SortOrder): ListSummary[] {
  const sorted = [...lists];
  // Notebooks carry no date: the server's order is the newest-first order.
  if (order === "old") sorted.reverse();
  if (order === "az") sorted.sort((a, b) => a.name.localeCompare(b.name, "vi"));
  if (order === "za") sorted.sort((a, b) => b.name.localeCompare(a.name, "vi"));
  return sorted;
}

// Notebooks of the language being learned come first.
function languageGroups(lists: ListSummary[], learning: string | null) {
  const codes = [...new Set(lists.map(list => list.languageCode))].sort((a, b) => Number(b === learning) - Number(a === learning));
  return codes.map(code => ({ code, lists: lists.filter(list => list.languageCode === code) }));
}

function Shelf({ language, lists, loading, failed, onRetry }: {
  language: string | null; lists: ListSummary[] | null; loading: boolean; failed: boolean; onRetry: () => void;
}) {
  const t = useT();
  const [order, setOrder] = useState<SortOrder>("new");
  const [creating, setCreating] = useState(false);
  const [sorting, setSorting] = useState(false);
  const [deleting, setDeleting] = useState<ListSummary | null>(null);
  const sortButton = useRef<HTMLButtonElement>(null);
  const sortPopover = useRef<HTMLDivElement>(null);
  const closeSort = useCallback(() => setSorting(false), []);
  useDismiss(sorting, closeSort, sortPopover, sortButton);

  const pair = (first: SortOrder, firstLabel: ReactNode, second: SortOrder, secondLabel: ReactNode) => <div className="nb-two-btn">
    <button type="button" aria-pressed={order === first} onClick={() => setOrder(first)}>{firstLabel}</button>
    <button type="button" aria-pressed={order === second} onClick={() => setOrder(second)}>{secondLabel}</button>
  </div>;

  return <div className="shelf-col">
    <div className="shelf-bar-top">
      <button type="button" className="shelf-create" onClick={() => setCreating(true)}><Icon name="plus" /><T>Create notebook</T></button>
      <div className="nb-pop-wrap">
        <button ref={sortButton} type="button" className="nb-round shelf-sort" aria-label={t("Sort notebooks")} aria-expanded={sorting} onClick={() => setSorting(value => !value)}><Icon name="filter" /></button>
        {sorting ? <div ref={sortPopover} className="nb-popover">
          <h3 className="shelf-pop-title"><T>Sort notebooks</T></h3>
          <div className="nb-lbl"><span><T>Time</T></span></div>
          {pair("new", <T>Newest</T>, "old", <T>Oldest</T>)}
          <div className="nb-lbl"><span><T>Name</T></span></div>
          {pair("az", <T>A-Z</T>, "za", <T>Z-A</T>)}
        </div> : null}
      </div>
    </div>

    {loading ? <p role="status"><T>Loading your notebooks…</T></p> : null}
    {failed ? (
      <div role="alert" className="shelf-card">
        <p className="error"><T>Your notebooks could not be loaded.</T></p>
        <button type="button" className="nb-btn" onClick={onRetry}><T>Retry</T></button>
      </div>
    ) : null}

    {languageGroups(lists ?? [], language).map(group => (
      <section key={group.code} className="shelf-card shelf-sec shelf-group" aria-labelledby={`shelf-${group.code}`}>
        <h2 id={`shelf-${group.code}`} className="shelf-title">
          <span lang={group.code}>{LANGUAGE_NAMES[group.code] ?? group.code.toUpperCase()}</span>
          {LANGUAGE_LABELS[group.code] && t(LANGUAGE_LABELS[group.code]) !== LANGUAGE_NAMES[group.code] ? <> · {t(LANGUAGE_LABELS[group.code])}</> : null}
        </h2>
        <ul className="shelf-tiles">
          {sortNotebooks(group.lists, order).map(list => <NotebookTile key={list.id} list={list} onDelete={() => setDeleting(list)} />)}
        </ul>
      </section>
    ))}
    {lists?.length === 0 ? (
      <div className="shelf-card shelf-empty"><Mascot state="listen" /><p><T>No notebooks yet.</T></p></div>
    ) : null}

    <ReadySets />

    {creating ? <CreateDialog language={language} onClose={() => setCreating(false)} /> : null}
    {deleting ? <DeleteDialog list={deleting} onClose={() => setDeleting(null)} /> : null}
  </div>;
}

function NotebookTile({ list, onDelete }: { list: ListSummary; onDelete: () => void }) {
  const t = useT();
  const [menu, setMenu] = useState<{ top: number; left: number } | null>(null);
  const kebab = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setMenu(null), []);
  useDismiss(menu !== null, close, popover, kebab);

  // The menu lives outside the scrolling row of tiles, so a scroll would leave it behind.
  useEffect(() => {
    if (!menu) return;
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [menu, close]);

  function toggle() {
    if (menu || !kebab.current) { setMenu(null); return; }
    const box = kebab.current.getBoundingClientRect();
    setMenu({ top: Math.min(box.bottom + 8, window.innerHeight - 56), left: Math.max(8, box.right - 128) });
  }

  return <li className="notebook-tile">
    <Link className="shelf-tile" to={`/words/lists/${encodeURIComponent(list.id)}`}>
      <strong title={list.name}>{list.name}</strong>
      <small><Icon name="book" />{t("{n} words", { n: list.wordCount })}</small>
    </Link>
    <button ref={kebab} type="button" className="shelf-kebab" aria-label={t("Options for {name}", { name: list.name })} aria-expanded={menu !== null} onClick={toggle}><Icon name="more" /></button>
    {menu ? createPortal(
      <div ref={popover} className="nb-popover small shelf-portal shelf-menu" style={menu}>
        <button type="button" className="nb-danger" autoFocus onClick={() => { kebab.current?.focus(); close(); onDelete(); }}><Icon name="trash" /><T>Delete</T></button>
      </div>, document.body) : null}
  </li>;
}

function ReadySets() {
  const t = useT();
  const { notebook } = useContainer();
  const [browsing, setBrowsing] = useState(false);
  const setsQuery = useQuery({ queryKey: ["word-sets"], queryFn: () => notebook.sets(), retry: false });
  if (setsQuery.isError) {
    return <section className="shelf-card shelf-sec" role="alert">
      <h2 className="shelf-title"><T>Ready-made sets</T></h2>
      <p className="error"><T>The ready-made sets could not be loaded.</T></p>
      <div><button type="button" className="nb-btn" onClick={() => void setsQuery.refetch()}><T>Retry</T></button></div>
    </section>;
  }
  const sets = setsQuery.data ?? [];
  if (sets.length === 0) return null;
  return <section className="shelf-card shelf-sec" aria-labelledby="shelf-sets">
    <div className="shelf-sec-head">
      <h2 id="shelf-sets" className="shelf-title"><T>Ready-made sets</T></h2>
      <button type="button" className="shelf-more" onClick={() => setBrowsing(true)}><T>See more</T></button>
    </div>
    <ul className="shelf-tiles shelf-tiles--two">
      {sets.map(set => <li key={set.key}>
        <Link className="shelf-tile" to={setPath(set)}>
          <strong title={set.name}>{set.name}</strong>
          <small><Icon name="book" />{t("{n} words", { n: set.wordCount })}</small>
        </Link>
      </li>)}
    </ul>
    {browsing ? <SetsDialog sets={sets} onClose={() => setBrowsing(false)} /> : null}
  </section>;
}

function setPath(set: WordSet): string {
  return `/words/sets/${encodeURIComponent(set.key)}`;
}

function SetsDialog({ sets, onClose }: { sets: WordSet[]; onClose: () => void }) {
  const t = useT();
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const shown = sets.filter(set => set.name.toLowerCase().includes(needle));
  return <ShelfDialog title={t("Search")} size="narrow" closeButton onClose={onClose}>
    <label className="nb-search shelf-search">
      <Icon name="search" />
      <input className="shelf-search__input" type="search" autoFocus placeholder={t("Search")} aria-label={t("Search sets")} value={query} onChange={event => setQuery(event.target.value)} />
    </label>
    <div className="nb-plist">
      {shown.map(set => <Link key={set.key} className="nb-pitem shelf-pitem" to={setPath(set)}>
        <span><strong>{set.name}</strong><small>{t("{n} words", { n: set.wordCount })}</small></span>
      </Link>)}
      {shown.length === 0 ? <p className="shelf-muted"><T>No sets match your search.</T></p> : null}
    </div>
  </ShelfDialog>;
}

function CreateDialog({ language, onClose }: { language: string | null; onClose: () => void }) {
  const t = useT();
  const { lists } = useContainer();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (listName: string) => lists.create(language ?? "", listName),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["word-lists"] });
      navigate(`/words/lists/${encodeURIComponent(created.id)}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed && language) create.mutate(trimmed);
  }

  return <ShelfDialog title={t("Create notebook")} onClose={onClose}>
    <form className="shelf-form" onSubmit={submit}>
      <input className="shelf-input" type="text" autoFocus aria-label={t("Notebook name")} placeholder={t("Enter your notebook name")} value={name} maxLength={60} onChange={event => setName(event.target.value)} />
      {create.isError ? <p className="error" role="alert">{createNotebookError(create.error)}</p> : null}
      <div className="nb-m-foot">
        <button type="button" className="nb-btn" onClick={onClose}><T>Cancel</T></button>
        <button type="submit" className="nb-btn main" disabled={!name.trim() || !language || create.isPending}><T>Add</T></button>
      </div>
    </form>
  </ShelfDialog>;
}

function DeleteDialog({ list, onClose }: { list: ListSummary; onClose: () => void }) {
  const t = useT();
  const { lists } = useContainer();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => lists.remove(list.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["word-lists"] });
      onClose();
    },
  });
  return <ShelfDialog title={t("Delete notebook?")} onClose={onClose}>
    <p>{t("“{name}” will be deleted. Its words stay in All words.", { name: list.name })}</p>
    {remove.isError ? <p className="error" role="alert"><T>The notebook could not be deleted. Please try again.</T></p> : null}
    <div className="nb-m-foot">
      <button type="button" className="nb-btn" onClick={onClose}><T>Cancel</T></button>
      <button type="button" className="nb-btn red" disabled={remove.isPending} onClick={() => remove.mutate()}><T>Delete</T></button>
    </div>
  </ShelfDialog>;
}

// Closes a popover on an outside press or Escape; Escape also returns focus to the button that opened it.
function useDismiss(open: boolean, onClose: () => void, popover: RefObject<HTMLElement>, trigger: RefObject<HTMLElement>) {
  useEffect(() => {
    if (!open) return;
    function press(event: PointerEvent) {
      const target = event.target as Node;
      if (!popover.current?.contains(target) && !trigger.current?.contains(target)) onClose();
    }
    function key(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      onClose();
      trigger.current?.focus();
    }
    document.addEventListener("pointerdown", press);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", press);
      document.removeEventListener("keydown", key);
    };
  }, [open, onClose, popover, trigger]);
}

export function ShelfDialog({ title, size = "tiny", closeButton = false, onClose, children }: {
  title: string; size?: "tiny" | "narrow"; closeButton?: boolean; onClose: () => void; children: ReactNode;
}) {
  const t = useT();
  const dialog = useModalDialog<HTMLDivElement>(onClose);
  const titleId = useId();
  return createPortal(
    <div className="nb-scrim nb-in shelf-portal" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialog} className={`nb-modal ${size}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="nb-m-head">
          <span id={titleId}>{title}</span>
          {closeButton ? <button type="button" aria-label={t("Close")} onClick={onClose}><Icon name="close" /></button> : null}
        </div>
        {children}
      </div>
    </div>, document.body);
}

export function createNotebookError(error: unknown): string {
  switch (listErrorCode(error)) {
    case "list_name_taken": return tr("You already have a notebook with that name.");
    case "too_many_lists": return tr("You have reached the limit of notebooks. Delete one first.");
    case "language_not_learned": return tr("Choose the language you are learning first.");
    default: return tr("The notebook could not be created. Please try again.");
  }
}
