import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { useParams } from "react-router-dom";
import type HanziWriterClass from "hanzi-writer";
import { useContainer } from "../../app/container";
import { Icon } from "../../design/notebookIcons";
import { T, useT } from "../../i18n/i18n";
import { ScopeState, StudyHeader, StudyMessage, StudySwitch } from "./StudyParts";
import { newEventId, type Answer, type AnswerResult } from "../review/reviewModels";
import { hanziOf, isHanWord } from "./studySession";
import { useScopeWords, type ScopeWord } from "./useScopeWords";

const GRID_SIZE = 280;
const CANVAS_SCALE = 2;

/** A finished word is sent to the server, which grades and logs it. Writing is practice: it never moves the schedule. */
function useWritingResult() {
  const { review } = useContainer();
  const [failed, setFailed] = useState(false);
  const send = useCallback(async (word: ScopeWord, answer: Answer, hintUsed: boolean): Promise<AnswerResult | null> => {
    setFailed(false);
    try {
      return await review.answer({ clientEventId: newEventId(), passId: null, conceptId: word.conceptId, languageCode: word.languageCode,
        exerciseType: "writing", answer, hintUsed, responseMs: null });
    } catch {
      setFailed(true);
      return null;
    }
  }, [review]);
  return { send, failed };
}
const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

interface CharUnit { char: string; reading: string | null }

/** One unit per distinct character of the words; a character's reading is its syllable of the word's reading. */
function charUnits(words: ScopeWord[]): CharUnit[] {
  const units = new Map<string, CharUnit>();
  for (const word of words) {
    const characters = hanziOf(word);
    const syllables = word.reading?.trim().split(/\s+/) ?? [];
    characters.forEach((char, index) => {
      const reading = characters.length === 1 ? word.reading : syllables.length === characters.length ? syllables[index] : null;
      const known = units.get(char);
      if (!known) units.set(char, { char, reading });
      else if (!known.reading && reading) known.reading = reading;
    });
  }
  return [...units.values()];
}

export function WritingScreen() {
  const { scope = "all" } = useParams();
  const t = useT();
  const loaded = useScopeWords(scope);
  const [showReading, setShowReading] = useState(true);
  const options = <StudySwitch label={t("Show reading")} on={showReading} onToggle={() => setShowReading(!showReading)} />;
  // Only Chinese and Japanese characters are written (stroke by stroke); other scripts have no writing practice.
  const hanWords = loaded.words.filter(isHanWord);
  return (
    <div className="st-page">
      <StudyHeader scope={scope} title={t("Writing practice")} options={options} />
      {loaded.isLoading || loaded.isError ? <ScopeState {...loaded} />
        : hanWords.length ? <WritingDesk words={hanWords} showReading={showReading} />
          : <StudyMessage><p>{loaded.words.length ? <T>This notebook has no Chinese or Japanese characters to write.</T> : <T>This notebook has no words yet.</T>}</p></StudyMessage>}
    </div>
  );
}

function WritingDesk({ words, showReading }: { words: ScopeWord[]; showReading: boolean }) {
  const t = useT();
  const units = charUnits(words);
  const [current, setCurrent] = useState(0);
  const [done, setDone] = useState<ReadonlySet<string>>(new Set());
  const [finished, setFinished] = useState(false);
  const [free, setFree] = useState(false);
  const [template, setTemplate] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [hinting, setHinting] = useState(false);
  const [query, setQuery] = useState("");

  const host = useRef<HTMLDivElement>(null);
  const writer = useRef<HanziWriterClass | null>(null);
  const canvas = useRef<FreeCanvasHandle | null>(null);

  const unit = units[Math.min(current, units.length - 1)];
  const character = unit.char;

  const result = useWritingResult();
  // Per word: which of its characters were written correctly in this visit and with how many mistakes.
  const progress = useRef(new Map<string, { written: Set<number>; mistakes: number; hinted: boolean; sent: boolean }>());
  const hinted = useRef(false);
  const live = useRef({ free, template, character, words, send: result.send });
  live.current = { free, template, character, words, send: result.send };

  const startQuiz = useCallback(() => {
    const active = writer.current;
    if (!active) return;
    active.cancelQuiz();
    void active.hideCharacter();
    if (live.current.free) { void active.hideOutline(); return; }
    void (live.current.template ? active.showOutline() : active.hideOutline());
    void Promise.resolve(active.quiz({
      onComplete: (summary?: { totalMistakes?: number }) => {
        const { character: written, words: all, send } = live.current;
        setFinished(true);
        setDone((before) => new Set(before).add(written));
        for (const word of all) {
          const characters = hanziOf(word);
          if (!characters.includes(written)) continue;
          const entry = progress.current.get(word.conceptId) ?? { written: new Set<number>(), mistakes: 0, hinted: false, sent: false };
          progress.current.set(word.conceptId, entry);
          characters.forEach((char, index) => { if (char === written) entry.written.add(index); });
          entry.mistakes += summary?.totalMistakes ?? 0;
          entry.hinted ||= hinted.current;
          if (!entry.sent && entry.written.size === characters.length) {
            entry.sent = true;
            void send(word, { text: characters.join(""), mistakes: entry.mistakes }, entry.hinted);
          }
        }
      },
    })).catch(() => setLoadFailed(true));
  }, []);

  // The library is loaded here, not at start-up, and fetches each character's strokes from its CDN.
  useEffect(() => {
    const target = host.current;
    if (!target) return;
    let active = true;
    let created: HanziWriterClass | null = null;
    setLoadFailed(false);
    setHinting(false);
    setFinished(false);
    hinted.current = false;
    target.innerHTML = "";
    void import("hanzi-writer").then(({ default: HanziWriter }) => {
      if (!active) return;
      created = HanziWriter.create(target, character, {
        width: GRID_SIZE, height: GRID_SIZE, padding: 14, showCharacter: false, showOutline: false,
        strokeColor: token("--label"), outlineColor: token("--separator"), drawingColor: token("--blue-strong"),
        highlightColor: token("--blue-strong"), drawingWidth: 12,
        onLoadCharDataError: () => {
          // The library throws on any call once loading failed, so nothing may reach it until a retry.
          if (active) { writer.current = null; setLoadFailed(true); }
        },
      });
      writer.current = created;
      startQuiz();
    }).catch(() => { if (active) setLoadFailed(true); });
    return () => {
      active = false;
      writer.current = null;
      try { created?.cancelQuiz(); } catch { /* the character never loaded */ }
      target.innerHTML = "";
    };
  }, [character, loadAttempt, startQuiz]);

  useEffect(() => { startQuiz(); setHinting(false); }, [free, startQuiz]);

  useEffect(() => {
    if (free || !writer.current) return;
    void (template ? writer.current.showOutline() : writer.current.hideOutline());
  }, [template, free]);

  function erase() {
    canvas.current?.clear();
    if (free) return;
    setFinished(false);
    setHinting(false);
    startQuiz();
  }

  function showStrokes() {
    const active = writer.current;
    if (!active || hinting) return;
    setHinting(true);
    hinted.current = true;
    active.cancelQuiz();
    void active.animateCharacter({
      onComplete: () => {
        setHinting(false);
        if (writer.current !== active) return;
        if (live.current.free) void active.hideCharacter(); else startQuiz();
      },
    });
  }

  const needle = query.trim().toLowerCase();
  const visible = units.map((item, index) => ({ item, index }))
    .filter(({ item }) => `${item.char} ${item.reading ?? ""}`.toLowerCase().includes(needle));

  return (
    <div className="st-wr">
      <section className="st-wr-main">
        <div className="st-wr-head">
          <span className="st-wr-char" lang="zh">{character}</span>
          {showReading && unit.reading ? <span className="st-wr-reading">{unit.reading}</span> : null}
          <StudySwitch label={t("Free writing")} on={free} onToggle={() => setFree(!free)} />
        </div>
        <div className="st-wr-grid">
          <svg className="st-wr-lines" viewBox="0 0 100 100" aria-hidden="true">
            <path d="M50 0V100M0 50H100M0 0L100 100M100 0L0 100" />
          </svg>
          <div ref={host} className={`st-wr-writer${free ? " behind" : ""}`} aria-label={t("Writing area")} role="group" />
          {free ? <FreeCanvas key={character} label={t("Writing area")} handle={canvas} /> : null}
        </div>
        {loadFailed ? (
          <div className="st-wr-failed" role="alert">
            <span><T>This character could not be loaded. Check your connection and try again.</T></span>
            <button type="button" className="nb-link" onClick={() => setLoadAttempt(loadAttempt + 1)}><T>Retry</T></button>
          </div>
        ) : null}
        {finished && !free ? <p className="st-done" role="status"><T>Well done. Every stroke is in place.</T></p> : null}
        {result.failed ? <p className="st-note" role="status"><T>Your result could not be saved.</T></p> : null}
        <div className="st-wr-tools">
          <button type="button" aria-label={t("Show stroke order")} disabled={loadFailed || hinting} onClick={showStrokes}><Icon name="hint" /></button>
          <button type="button" aria-label={t("Erase")} onClick={erase}><Icon name="erase" /></button>
          <button type="button" aria-label={t("Show template")} aria-pressed={template} disabled={free} onClick={() => setTemplate(!template)}><Icon name="eye" /></button>
        </div>
      </section>
      <aside className="st-wr-side">
        <label className="nb-search"><Icon name="search" /><input value={query} placeholder={t("Search")} aria-label={t("Find a character")} onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="st-wr-list">
          {visible.map(({ item, index }) => (
            <button key={item.char} type="button" className={`${index === current ? "on" : ""}${done.has(item.char) ? " done" : ""}`}
              aria-current={index === current ? "true" : undefined} onClick={() => setCurrent(index)}>
              <small>{item.reading}</small><span lang="zh">{item.char}</span>
            </button>
          ))}
        </div>
      </aside>
    </div>
  );
}

interface FreeCanvasHandle { clear: () => void }

// Free writing has nothing to check: the learner draws on a blank square.
function FreeCanvas({ label, handle }: { label: string; handle: React.MutableRefObject<FreeCanvasHandle | null> }) {
  const node = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);

  useEffect(() => {
    const context = node.current?.getContext?.("2d");
    if (!context || !node.current) return;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.lineWidth = 14;
    context.strokeStyle = token("--label");
    const size = node.current.width;
    handle.current = { clear: () => context.clearRect(0, 0, size, size) };
    return () => { handle.current = null; };
  }, [handle]);

  const point = (event: PointerEvent<HTMLCanvasElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return [(event.clientX - box.left) * CANVAS_SCALE, (event.clientY - box.top) * CANVAS_SCALE] as const;
  };
  return (
    <canvas ref={node} className="st-wr-canvas" width={GRID_SIZE * CANVAS_SCALE} height={GRID_SIZE * CANVAS_SCALE} aria-label={label} role="img"
      onPointerDown={(event) => {
        drawing.current = true;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        const context = event.currentTarget.getContext("2d");
        context?.beginPath();
        context?.moveTo(...point(event));
      }}
      onPointerMove={(event) => {
        if (!drawing.current) return;
        const context = event.currentTarget.getContext("2d");
        context?.lineTo(...point(event));
        context?.stroke();
      }}
      onPointerUp={() => { drawing.current = false; }} onPointerCancel={() => { drawing.current = false; }} />
  );
}
