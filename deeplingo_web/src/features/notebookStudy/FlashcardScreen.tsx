import { useEffect, useRef, useState, type FormEvent, type MouseEvent, type PointerEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { Icon } from "../../design/notebookIcons";
import { Mascot } from "../../design/Mascot";
import { T, tr, useT } from "../../i18n/i18n";
import type { MemoryRating } from "../words/notebookApi";
import { useWordAudio } from "../words/useWordAudio";
import { ExampleSource, ScopeState, SpeedSlider, StudyDialog, StudyHeader, StudyMessage, StudySwitch } from "./StudyParts";
import { scopeHref, shortGloss } from "./studySession";
import { useScopeWords, type ScopeWord } from "./useScopeWords";

const MEMORY: { value: MemoryRating; title: string; icon: "close" | "question" | "check"; tone: string }[] = [
  { value: "not_yet", title: "Not yet", icon: "close", tone: "x" },
  { value: "unsure", title: "Unsure", icon: "question", tone: "q" },
  { value: "remembered", title: "Remembered", icon: "check", tone: "ok" },
];
const SWIPE_DISTANCE = 110;
const DRAG_START = 6;
const AUTOPLAY_MS = 1800;

export function FlashcardScreen() {
  const { scope = "all" } = useParams();
  const t = useT();
  const loaded = useScopeWords(scope);
  const [round, setRound] = useState(0);
  const ready = !loaded.isLoading && !loaded.isError;
  if (!ready) return <div className="st-page"><StudyHeader scope={scope} title={t("Flashcard")} /><ScopeState {...loaded} /></div>;
  if (loaded.words.length === 0) return <div className="st-page"><StudyHeader scope={scope} title={t("Flashcard")} /><StudyMessage><p><T>This notebook has no words yet.</T></p></StudyMessage></div>;
  return <FlashcardDeck key={round} scope={scope} cards={loaded.words} patch={loaded.patch} onRestart={() => setRound(round + 1)} />;
}

function FlashcardDeck({ scope, cards, patch, onRestart }: {
  scope: string; cards: ScopeWord[]; patch: (conceptId: string, change: Partial<ScopeWord>) => void; onRestart: () => void;
}) {
  const t = useT();
  const { notebook, words } = useContainer();
  const audio = useWordAudio();
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [history, setHistory] = useState<number[]>([]);
  const [ratings, setRatings] = useState<Record<string, MemoryRating>>({});
  // As in Hanzii, the last rating can be taken back with one step back. It is sent when the next card is
  // rated, when the deck ends or when the page closes, so the schedule moves once per card.
  const [pending, setPending] = useState<{ conceptId: string; rating: MemoryRating } | null>(null);
  const [undone, setUndone] = useState(false);
  const sent = useRef(new Set<string>());
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoplay, setAutoplay] = useState(false);
  const [dialog, setDialog] = useState<"search" | "note" | null>(null);
  const [showReading, setShowReading] = useState(true);
  const [speed, setSpeed] = useState(1);

  const cardNode = useRef<HTMLDivElement>(null);
  const drag = useRef<{ startX: number; dx: number } | null>(null);
  const justDragged = useRef(false);

  const card: ScopeWord | undefined = cards[index];
  const rated = card ? ratings[card.conceptId] : undefined;
  const example = useQuery({
    queryKey: ["word-examples-read", card?.conceptId],
    queryFn: () => words.examples(card!.conceptId, true),
    enabled: !!card && flipped,
    retry: false,
  }).data?.[0];

  function goTo(next: number) {
    setHistory((visited) => [...visited, index]);
    setIndex(next);
    setFlipped(false);
    setError(null);
    setUndone(false);
  }
  const advance = () => goTo(index + 1);
  const canUndo = history.length > 0 && !undone;

  function back() {
    if (!canUndo) return;
    const previous = history[history.length - 1];
    const previousId = cards[previous]?.conceptId;
    setIndex(previous);
    setHistory(history.slice(0, -1));
    setFlipped(false);
    setError(null);
    setAutoplay(false);
    setUndone(true);
    if (pending && pending.conceptId === previousId) {
      setPending(null);
      setRatings(({ [previousId]: _taken, ...rest }) => rest);
    }
  }

  async function send(rating: { conceptId: string; rating: MemoryRating }): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await notebook.rateMemory(rating.conceptId, rating.rating);
    } catch {
      setError(tr("Your rating could not be saved. Try again."));
      return false;
    } finally {
      setBusy(false);
    }
    sent.current.add(rating.conceptId);
    setPending((current) => (current === rating ? null : current));
    return true;
  }

  const finished = index >= cards.length;
  useEffect(() => {
    if (finished && pending) void send(pending);
    // Only the end of the deck sends here; send reads the pending rating passed in.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);

  useEffect(() => {
    const leave = () => {
      const last = pendingRef.current;
      if (!last) return;
      pendingRef.current = null;
      setPending(null);
      void notebook.rateMemory(last.conceptId, last.rating, true).catch(() => {});
    };
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); leave(); };
  }, [notebook]);

  useEffect(() => {
    if (!autoplay || dialog || index >= cards.length) return;
    const timer = window.setTimeout(() => {
      if (flipped) goTo(index + 1); else setFlipped(true);
    }, AUTOPLAY_MS);
    return () => window.clearTimeout(timer);
    // goTo only reads the index listed here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoplay, dialog, flipped, index, cards.length]);

  async function rateMemory(rating: MemoryRating) {
    if (!card || busy) return;
    setAutoplay(false);
    if (sent.current.has(card.conceptId)) { advance(); return; } // Its rating already reached the schedule.
    if (pending && pending.conceptId !== card.conceptId && !(await send(pending))) return;
    setPending({ conceptId: card.conceptId, rating });
    setRatings((current) => ({ ...current, [card.conceptId]: rating }));
    advance();
  }

  async function savePersonal(change: { favorite?: boolean; note?: string | null }, local: Partial<ScopeWord>): Promise<boolean> {
    if (!card || busy) return false;
    setBusy(true);
    setError(null);
    try {
      await notebook.setPersonal(card.conceptId, change);
      patch(card.conceptId, local);
      return true;
    } catch {
      setError(tr("That could not be saved. Try again."));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const flip = () => { setFlipped((value) => !value); setError(null); };

  function onCardClick(event: MouseEvent<HTMLDivElement>) {
    if (justDragged.current) { justDragged.current = false; return; }
    if ((event.target as HTMLElement).closest("button,a")) return;
    flip();
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest("button,a")) return;
    drag.current = { startX: event.clientX, dx: 0 };
    justDragged.current = false;
  }
  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    drag.current.dx = event.clientX - drag.current.startX;
    if (Math.abs(drag.current.dx) > DRAG_START && cardNode.current) {
      cardNode.current.style.transform = `translateX(${drag.current.dx}px) rotate(${drag.current.dx / 18}deg)`;
    }
  }
  function endDrag() {
    if (!drag.current) return;
    const { dx } = drag.current;
    drag.current = null;
    if (cardNode.current) cardNode.current.style.transform = "";
    if (Math.abs(dx) > DRAG_START) justDragged.current = true;
    if (dx > SWIPE_DISTANCE) void rateMemory("remembered");
    else if (dx < -SWIPE_DISTANCE) void rateMemory("not_yet");
  }

  const options = <>
    <StudySwitch label={t("Show reading")} on={showReading} onToggle={() => setShowReading(!showReading)} />
    <div className="nb-sep" />
    <SpeedSlider speed={speed} onChange={setSpeed} />
  </>;

  if (!card) {
    const count = (rating: MemoryRating) => Object.values(ratings).filter((value) => value === rating).length;
    return (
      <div className="st-page">
        <StudyHeader scope={scope} title={t("Flashcard")} />
        <StudyMessage>
          <Mascot state="happy" className="st-summary-mascot" />
          <b className="st-summary-score">{count("remembered")}/{cards.length}</b>
          <p><T a={count("remembered")} b={count("unsure")} c={count("not_yet")}>{"Remembered {a} · Unsure {b} · Not yet {c}"}</T></p>
          {error ? <p className="st-error" role="alert">{error}</p> : null}
          {error && pending ? <button type="button" className="nb-btn" disabled={busy} onClick={() => void send(pending)}><T>Try again</T></button> : null}
          <div className="nb-row-between">
            <Link className="nb-btn" to={scopeHref(scope)}><T>Back to notebook</T></Link>
            <button type="button" className="nb-btn main" onClick={onRestart}><T>Study again</T></button>
          </div>
        </StudyMessage>
      </div>
    );
  }

  const say = () => void audio.play(card.languageCode, card.text, speed, card.conceptId);
  const heart = (visible: boolean, side: string) => (
    <button type="button" className={`st-corner ${side}${card.favorite ? " on" : ""}`} tabIndex={visible ? 0 : -1} aria-pressed={card.favorite}
      aria-label={t("Favorite")} onClick={() => void savePersonal({ favorite: !card.favorite }, { favorite: !card.favorite })}><Icon name="heart" /></button>
  );
  const position = <div className="st-corner-count">{index + 1} / {cards.length}</div>;
  const count = (rating: MemoryRating) => Object.values(ratings).filter((value) => value === rating).length;

  return (
    <div className="st-page">
      <StudyHeader scope={scope} title={t("Flashcard")} options={options} />
      <div className="st-fc-wrap">
        <div className="st-fc-bg" />
        <div ref={cardNode} className={`st-fc${flipped ? " flip" : ""}`} data-testid="flashcard" onClick={onCardClick}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerLeave={endDrag} onPointerCancel={endDrag}>
          <button type="button" className="st-fc-key" aria-label={t(flipped ? "Show the word" : "Show the answer")} onClick={flip} />
          <div className="st-fc-in">
            <div className="st-face" aria-hidden={flipped}>
              {heart(!flipped, "tl")}
              {position}
              <button type="button" className="st-corner tr" tabIndex={flipped ? -1 : 0} aria-label={t("Listen")} onClick={say}><Icon name="sound" /></button>
              <div className={`st-face-big${card.text.length > 6 ? " long" : ""}`} lang={card.languageCode}>{card.text}</div>
            </div>
            <div className="st-face st-face-back" aria-hidden={!flipped}>
              {heart(flipped, "tr")}
              {position}
              <div className="st-face-big answer" lang={card.languageCode}>{card.text}{card.traditional ? <small>【{card.traditional}】</small> : null}</div>
              <div className="st-reading st-fc-reading">
                {showReading && card.reading ? <span>{card.reading}</span> : null}
                <button type="button" tabIndex={flipped ? 0 : -1} aria-label={t("Listen")} onClick={say}><Icon name="sound" /></button>
              </div>
              <div className="st-fc-mean">{card.gloss}</div>
              {example ? <>
                <div className="nb-sep st-fill" />
                <div className="st-example">
                  <b lang={card.languageCode}>{example.text}</b>
                  {example.translation ? <span>{example.translation}</span> : null}
                  <ExampleSource example={example} />
                </div>
              </> : null}
              {card.note ? <p className="st-fc-notetext">{card.note}</p> : null}
              <button type="button" className={`st-note-chip${card.note ? " has" : ""}`} tabIndex={flipped ? 0 : -1} onClick={() => setDialog("note")}>
                <Icon name="note" /><T>Note</T>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="st-fc-tools">
        <button type="button" aria-label={t("Find a card")} onClick={() => setDialog("search")}><Icon name="search" /></button>
        <button type="button" aria-label={t("Previous card")} disabled={!canUndo || busy} onClick={back}><Icon name="undo" /></button>
        <button type="button" className="pl" aria-label={t("Auto-play")} aria-pressed={autoplay} onClick={() => setAutoplay(!autoplay)}><Icon name={autoplay ? "stop" : "play"} /></button>
        <div className="st-fc-memory" role="group" aria-label={t("Memory")}>
          {MEMORY.map((item) => (
            <button key={item.value} type="button" className={item.tone} aria-label={t(item.title)} title={t(item.title)}
              aria-pressed={rated === item.value} disabled={busy} onClick={() => void rateMemory(item.value)}>
              <Icon name={item.icon} />
              <span className="st-fc-mem-lbl"><T>{item.title}</T></span>
            </button>
          ))}
        </div>
      </div>

      {error ? <p className="st-error st-center" role="alert">{error}</p> : null}
      {audio.failed ? <p className="st-note st-center" role="status"><T>Audio is not available for this word.</T></p> : null}
      <div className="st-fc-tally">
        <span><T>Memory</T>:</span>
        <span><T n={count("not_yet")}>{"Not yet {n}"}</T></span>
        <span><T n={count("unsure")}>{"Unsure {n}"}</T></span>
        <span><T n={count("remembered")}>{"Remembered {n}"}</T></span>
      </div>

      {dialog === "search" ? <CardSearch cards={cards} onClose={() => setDialog(null)} onPick={(i) => { setDialog(null); if (i !== index) goTo(i); }} /> : null}
      {dialog === "note" ? <NoteDialog initial={card.note} error={error} onClose={() => setDialog(null)}
        onSave={async (note) => { if (await savePersonal({ note }, { note })) setDialog(null); }} /> : null}
    </div>
  );
}

function CardSearch({ cards, onPick, onClose }: { cards: ScopeWord[]; onPick: (index: number) => void; onClose: () => void }) {
  const t = useT();
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const matches = cards.map((card, index) => ({ card, index }))
    .filter(({ card }) => `${card.text} ${card.reading ?? ""} ${card.gloss ?? ""}`.toLowerCase().includes(needle));
  return (
    <StudyDialog label={t("Find a card")} className="tiny" onClose={onClose}>
      <div className="nb-m-head"><span><T>Find a card</T></span><button type="button" aria-label={t("Close")} onClick={onClose}><Icon name="close" /></button></div>
      <label className="nb-search st-tile-search"><Icon name="search" /><input value={query} placeholder={t("Search")} aria-label={t("Find a card")} onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="nb-plist">
        {matches.map(({ card, index }) => (
          <button key={card.conceptId} type="button" className="nb-pitem" onClick={() => onPick(index)}>
            <span><strong lang={card.languageCode}>{card.text}</strong><small>{shortGloss(card)}</small></span>
          </button>
        ))}
      </div>
    </StudyDialog>
  );
}

function NoteDialog({ initial, error, onSave, onClose }: { initial: string | null; error: string | null; onSave: (note: string | null) => Promise<void>; onClose: () => void }) {
  const t = useT();
  const [text, setText] = useState(initial ?? "");
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    await onSave(text.trim() || null);
    setSaving(false);
  }
  return (
    <StudyDialog label={t(initial ? "Edit note" : "Add a note")} className="tiny" onClose={onClose}>
      <form className="st-note-form" onSubmit={(event) => void submit(event)}>
        <div className="nb-m-head"><span>{t(initial ? "Edit note" : "Add a note")}</span></div>
        <textarea className="nb-input" value={text} placeholder={t("Write your note")} aria-label={t("Note")} onChange={(event) => setText(event.target.value)} />
        {error ? <p className="st-error" role="alert">{error}</p> : null}
        <div className="nb-m-foot">
          <button type="button" className="nb-btn" onClick={onClose}><T>Cancel</T></button>
          <button className="nb-btn main" disabled={saving}><T>Save</T></button>
        </div>
      </form>
    </StudyDialog>
  );
}
