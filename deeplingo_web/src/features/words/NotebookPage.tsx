import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { Icon } from "../../design/notebookIcons";
import { Mascot } from "../../design/Mascot";
import { T, useT, tr } from "../../i18n/i18n";
import { PronounceDialog } from "../notebookStudy/PronounceDialog";
import { ReviewSetupSheet } from "../notebookStudy/ReviewSetupSheet";
import { isHanWord, scopePath } from "../notebookStudy/studySession";
import { listErrorCode, type ListSummary, type WaitingLine } from "./listsModels";
import { AddWordDialog } from "./notebook/AddWordDialog";
import { ConfirmDialog } from "./notebook/ConfirmDialog";
import { DEFAULT_SHOW, filterWords, orderWords, toStudyWord, type NotebookWord, type ShowOptions, type WordOrder } from "./notebook/model";
import { MoveDialog } from "./notebook/MoveDialog";
import { NoteDialog } from "./notebook/NoteDialog";
import { OptionsPopover } from "./notebook/OptionsPopover";
import { PasteDialog } from "./notebook/PasteDialog";
import { useWordImages } from "./notebook/useWordImages";
import { WaitingDialog } from "./notebook/WaitingDialog";
import { WordSheet } from "./notebook/WordSheet";
import { WordTile } from "./notebook/WordTile";
import { useWordAudio } from "./useWordAudio";
import "./notebook-base.css";
import "./notebook.css";

// Only one dialog at a time. A dialog opened from the word sheet goes back to it when it closes.
type Modal =
  | { kind: "add" | "paste" | "waiting" | "move" | "review" | "delete-notebook" }
  | { kind: "word"; id: string }
  | { kind: "note"; id: string; back?: boolean }
  | { kind: "remove"; ids: string[] | null; back?: string }
  | { kind: "pronounce"; index: number };

// One notebook, All words or one level of the shelf chart: the same page with a different set of words.
export function NotebookPage({ scope, title, languageCode, words: source, listId, waiting = [], children }: {
  scope: string; // A notebook id, "all", or "level-0" .. "level-4".
  title: string;
  languageCode: string;
  words: NotebookWord[];
  listId: string | null;
  waiting?: WaitingLine[];
  children?: ReactNode;
}) {
  const t = useT();
  const { lists, words } = useContainer();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const audio = useWordAudio();
  const [show, setShow] = useState<ShowOptions>(DEFAULT_SHOW);
  const [order, setOrder] = useState<WordOrder>("newest");
  const [query, setQuery] = useState("");
  const [withPictures, setWithPictures] = useState(false);
  const [selected, setSelected] = useState<Set<string> | null>(null); // null while not selecting
  const [modal, setModal] = useState<Modal | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const grid = useRef<HTMLUListElement | null>(null);
  // Fresh for a moment, so All words (which loads the same list first) does not fetch it twice; invalidation still refreshes it.

  const refresh = () => {
    for (const key of ["word-list", "word-lists", "my-words"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const ordered = useMemo(() => orderWords(source, order, languageCode), [source, order, languageCode]);
  const shown = useMemo(() => filterWords(ordered, query), [ordered, query]);
  const shownIds = useMemo(() => shown.map(word => word.conceptId), [shown]);
  const { images, putImage } = useWordImages(withPictures, shownIds, grid);
  const study = useMemo(() => source.map(toStudyWord), [source]);
  const autoplay = useAutoplay(shown, audio);

  const bulk = useMutation({
    // One word at a time; a word already handled leaves the selection, so trying again finishes the rest.
    mutationFn: async ({ ids, target }: { ids: string[]; target: ListSummary | null }) => {
      for (const conceptId of ids) {
        if (target) await lists.addWord(target.id, conceptId);
        if (listId) await lists.removeWord(listId, conceptId);
        else if (!target) await words.remove(conceptId);
        setSelected(current => {
          if (!current) return current;
          const next = new Set(current);
          next.delete(conceptId);
          return next;
        });
      }
    },
    onSuccess: (_result, { ids, target }) => {
      setSelected(null);
      setModal(null);
      if (target) setNotice(listId ? tr("Moved {n} words to “{name}”", { n: ids.length, name: target.name }) : tr("Added {n} words to “{name}”", { n: ids.length, name: target.name }));
      else setNotice(listId ? tr("Removed {n} words from this notebook", { n: ids.length }) : tr("Removed {n} words", { n: ids.length }));
    },
    onSettled: refresh,
  });
  const removeList = useMutation({
    mutationFn: () => lists.remove(listId ?? ""),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["word-lists"] });
      navigate("/words/lists");
    },
  });

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 2400);
    return () => window.clearTimeout(timer);
  }, [notice]);
  const waitingDone = modal?.kind === "waiting" && waiting.length === 0;
  useEffect(() => { if (waitingDone) setModal(null); }, [waitingDone]);

  const close = () => {
    bulk.reset();
    setModal(current => {
      if (current?.kind === "note" && current.back) return { kind: "word", id: current.id };
      if (current?.kind === "remove" && current.back) return { kind: "word", id: current.back };
      return null;
    });
  };
  const leaveSelection = () => { setSelected(null); bulk.reset(); };
  const toggleWord = (conceptId: string) => setSelected(current => {
    const next = new Set(current);
    if (!next.delete(conceptId)) next.add(conceptId);
    return next;
  });
  const allShownSelected = shown.length > 0 && selected !== null && shown.every(word => selected.has(word.conceptId));
  const toggleAllShown = () => setSelected(allShownSelected ? new Set() : new Set(shownIds));
  const empty = source.length === 0;
  const selectedIds = [...(selected ?? [])];
  const tata = `/agent?mode=voice&practice=roleplay&entry=home${listId ? `&topic=${encodeURIComponent(listId)}` : ""}`;
  const openWord = (id: string) => source.find(word => word.conceptId === id);

  return <section className={selected ? "nbp-page is-selecting" : "nbp-page"}>
    <header className="nbp-head">
      <Link className="nbp-pill nbp-back" to="/words/lists"><Icon name="back" /><T>Back</T></Link>
      <h1>{title}</h1>
      <div className="nbp-meta"><span><Icon name="book" />{t("{n} words", { n: source.length })}</span></div>
      <OptionsPopover show={show} onShow={setShow} order={order} onOrder={setOrder}
                      onPaste={listId ? () => setModal({ kind: "paste" }) : undefined} />
    </header>

    <div className="nbp-layout">
      <div className="nbp-main">
        <section className="nbp-card" aria-labelledby="nbp-words-heading">
          <h2 id="nbp-words-heading" className="sr-only"><T>Words</T></h2>
          <div className="nbp-bar">
            {selected ? <>
              <button type="button" className="nb-chip-btn" onClick={toggleAllShown}>
                <span className={allShownSelected ? "nbp-mini-pick on" : "nbp-mini-pick"} aria-hidden="true" />
                <T>Select all</T>
              </button>
              <span className="nbp-bar__count" role="status"><T n={selected.size}>{"{n} selected"}</T></span>
              <button type="button" className="nb-chip-btn" disabled={bulk.isPending} onClick={leaveSelection}><Icon name="close" /><T>Cancel</T></button>
            </> : <>
              <button type="button" className="nb-chip-btn" onClick={() => setModal({ kind: "add" })}><Icon name="plus" /><T>Add word</T></button>
              <button type="button" className="nb-chip-btn" disabled={empty} onClick={() => setSelected(new Set())}><Icon name="edit" /><T>Edit</T></button>
              <span className="nb-viewtog" role="group" aria-label={t("View")}>
                <button type="button" aria-pressed={withPictures} aria-label={t("Show pictures")} title={t("Show pictures")} onClick={() => setWithPictures(true)}><Icon name="image" /></button>
                <button type="button" aria-pressed={!withPictures} aria-label={t("Show as a list")} title={t("Show as a list")} onClick={() => setWithPictures(false)}><Icon name="list" /></button>
              </span>
            </>}
          </div>

          {waiting.length > 0 && !selected ? <button type="button" className="nbp-waiting-banner" onClick={() => setModal({ kind: "waiting" })}>
            <Icon name="hint" /><span><T n={waiting.length}>{"{n} words need a meaning"}</T></span><Icon name="chevron" />
          </button> : null}

          {empty ? <div className="nbp-empty">
            <Mascot state="listen" />
            <p><T>No words in this notebook yet.</T></p>
            <button type="button" className="nb-btn main" onClick={() => setModal({ kind: "add" })}><T>Add word</T></button>
          </div> : shown.length === 0 ? <div className="nbp-empty"><p><T>No words here.</T></p></div> : <ul className="nbp-words" ref={grid}>
            {shown.map(word => <WordTile key={word.conceptId} word={word} show={show} withPicture={withPictures} picture={images[word.conceptId]}
              selecting={selected !== null} selected={selected?.has(word.conceptId) ?? false} playing={audio.playing === word.text}
              onOpen={() => setModal({ kind: "word", id: word.conceptId })} onToggle={() => toggleWord(word.conceptId)}
              onNote={() => setModal({ kind: "note", id: word.conceptId })} onPlay={() => void audio.play(word.languageCode, word.text, 1, word.conceptId)} />)}
          </ul>}
          {audio.failed ? <p className="small muted" role="status"><T>This word could not be played.</T></p> : null}

          {shown.length > 0 && !selected ? <button type="button" className="nbp-autoplay" aria-pressed={autoplay.running} onClick={autoplay.toggle}>
            <i><Icon name={autoplay.running ? "stop" : "play"} /></i>{autoplay.running ? <T>Stop</T> : <T>Play all</T>}
          </button> : null}
        </section>
        {children}
      </div>

      <aside className="nbp-side">
        <label className="nb-search">
          <Icon name="search" />
          <input type="search" aria-label={t("Search words")} placeholder={t("Search")} value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <div className="nbp-study">
          <button type="button" disabled={empty} onClick={() => setModal({ kind: "review" })}><span><T>Review</T></span><Icon name="folder" /></button>
          <button type="button" className="mic" disabled={empty} onClick={() => setModal({ kind: "pronounce", index: 0 })}><span><T>Pronunciation</T></span><Icon name="mic" /></button>
          {study.some(isHanWord) ? <Link className="pen" to={scopePath(scope, "writing")}><span><T>Writing</T></span><Icon name="pen" /></Link> : null}
          <Link className="flash" to={scopePath(scope, "flashcards")}><span><T>Flashcards</T></span><Icon name="cards" /></Link>
        </div>
        <Link className="nbp-banner" to={tata}>
          <Mascot state="listen" />
          <span><strong><T>Practise with Tata</T></strong><small>{t("{n} words", { n: source.length })}</small></span>
          <span className="nbp-banner__go"><T>Start speaking</T><Icon name="chevron" /></span>
        </Link>
        {listId ? <div className="nbp-delete">
          <button type="button" className="nb-danger" onClick={() => setModal({ kind: "delete-notebook" })}><T>Delete notebook</T></button>
        </div> : null}
      </aside>
    </div>

    {selected ? <div className="nbp-float" role="region" aria-label={t("Select words")}>
      <button type="button" className="nb-danger" disabled={selectedIds.length === 0 || bulk.isPending} onClick={() => setModal({ kind: "remove", ids: null })}><Icon name="trash" /><T>Delete</T></button>
      <button type="button" disabled={selectedIds.length !== 1 || bulk.isPending} onClick={() => setModal({ kind: "note", id: selectedIds[0] })}><Icon name="edit" /><T>Edit word</T></button>
      <button type="button" disabled={selectedIds.length === 0 || bulk.isPending} onClick={() => setModal({ kind: "move" })}><Icon name="move" />{listId ? <T>Move</T> : <T>Add to notebook</T>}</button>
    </div> : null}

    {notice ? <div className="nbp-toast" role="status">{notice}</div> : null}

    {modal?.kind === "add" ? <AddWordDialog languageCode={languageCode} listId={listId} onChanged={refresh} onClose={close} /> : null}
    {modal?.kind === "paste" && listId ? <PasteDialog listId={listId} onChanged={refresh} onClose={close} /> : null}
    {modal?.kind === "waiting" && listId ? <WaitingDialog listId={listId} lines={waiting} onChanged={refresh} onClose={close} /> : null}
    {modal?.kind === "review" ? <ReviewSetupSheet scope={scope} words={study} preselected={study.slice(0, 5).map(word => word.conceptId)} onClose={close} /> : null}
    {modal?.kind === "pronounce" ? <PronounceDialog words={study} initialIndex={modal.index} onClose={close} /> : null}
    {modal?.kind === "note" ? (() => {
      const word = openWord(modal.id);
      return word ? <NoteDialog key={word.conceptId} word={word} onChanged={refresh} onClose={close} /> : null;
    })() : null}
    {modal?.kind === "word" ? (() => {
      const word = openWord(modal.id);
      if (!word) return null;
      return <WordSheet key={word.conceptId} word={word} inNotebook={listId !== null} image={images[word.conceptId]}
        playing={audio.playing === word.text} audioFailed={audio.failed} onPlay={() => void audio.play(word.languageCode, word.text, 1, word.conceptId)}
        onImage={image => putImage(word.conceptId, image)} onChanged={refresh}
        onPronounce={() => setModal({ kind: "pronounce", index: Math.max(0, study.findIndex(item => item.conceptId === word.conceptId)) })}
        onNote={() => setModal({ kind: "note", id: word.conceptId, back: true })}
        onRemove={() => setModal({ kind: "remove", ids: [word.conceptId], back: word.conceptId })}
        onClose={close} />;
    })() : null}
    {modal?.kind === "remove" ? (() => {
      const ids = modal.ids ?? selectedIds;
      return <ConfirmDialog
        title={listId ? t("Remove {n} words from this notebook?", { n: ids.length }) : t("Remove {n} words?", { n: ids.length })}
        body={listId ? <T>They stay in All words.</T> : <T>They will be removed from All words and from every notebook.</T>}
        action={listId ? t("Remove from notebook") : t("Remove word")}
        busy={bulk.isPending} error={bulk.isError ? bulkError(bulk.error) : null}
        onConfirm={() => bulk.mutate({ ids, target: null })} onClose={close} />;
    })() : null}
    {modal?.kind === "move" ? <MoveDialog title={listId ? t("Move words") : t("Add to notebook")} languageCode={languageCode} currentListId={listId}
      busy={bulk.isPending} error={bulk.isError ? bulkError(bulk.error) : null}
      onDone={target => bulk.mutate({ ids: selectedIds, target })} onClose={close} /> : null}
    {modal?.kind === "delete-notebook" ? <ConfirmDialog title={t("Delete notebook?")} body={<T name={title}>{"“{name}” will be deleted. Its words stay in All words."}</T>} action={t("Delete")}
      busy={removeList.isPending} error={removeList.isError ? tr("The notebook could not be deleted. Please try again.") : null}
      onConfirm={() => removeList.mutate()} onClose={close} /> : null}
  </section>;
}

function bulkError(error: unknown): string {
  return listErrorCode(error) === "list_full" ? tr("That notebook is full. Remove a word from it first.") : tr("Some words could not be changed. Please try again.");
}

// Reads the words on screen in order. Stop lets the word being read finish and goes no further.
function useAutoplay(words: readonly NotebookWord[], audio: ReturnType<typeof useWordAudio>) {
  const [index, setIndex] = useState<number | null>(null);
  const started = useRef(false);
  const { play, playing, failed } = audio;
  const word = index === null ? undefined : words[index];
  const text = word?.text;
  const language = word?.languageCode;
  const conceptId = word?.conceptId;

  useEffect(() => {
    if (index === null) return;
    if (text === undefined || language === undefined) { setIndex(null); return; }
    started.current = false;
    void play(language, text, 1, conceptId);
  }, [index, text, language, conceptId, play]);

  useEffect(() => {
    if (index === null) return;
    if (playing) started.current = true;
    else if (started.current) {
      started.current = false;
      setIndex(failed ? null : current => (current === null ? null : current + 1));
    }
  }, [index, playing, failed]);

  return { running: index !== null, toggle: () => setIndex(current => (current === null ? 0 : null)) };
}
