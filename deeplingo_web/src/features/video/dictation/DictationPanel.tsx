import { useEffect, useMemo, useRef, useState } from "react";
import type { TranscriptSegmentView } from "../../../lib/api/dto";
import {
  correctCount,
  diffAnswer,
  dictationTokens,
  isPerfect,
  lengthHint,
  shuffledTokens,
  type DictationLevel,
  type DiffItem,
} from "./dictationModel";
import { T, useT } from "../../../i18n/i18n";

const SPEEDS = [0.5, 0.75, 1, 1.25];
const REPEATS = [1, 2, 3];

type Phase = "setup" | "listening" | "answering" | "checked" | "done";

interface Result {
  perfect: boolean;
  correct: number;
  total: number;
}

export interface DictationCheck {
  segment_id: string;
  level: DictationLevel;
  answer: string;
  hint_shown: boolean;
}

export interface DictationPlayer {
  playClip: (startMs: number, endMs: number, onEnd?: () => void) => void;
  pause: () => void;
  setRate: (rate: number) => void;
}

// Sentence-by-sentence dictation beside the video (legacy mobile UX): the player plays
// one sentence, pauses, and the learner arranges (easy) or types (hard) what they heard.
// The comparison shown here is local. Each checked answer is also reported through onChecked
// (M1 S4 practice log): the server re-checks it; it is never a score or learning Evidence.
export function DictationPanel({
  segments,
  languageCode,
  unspaced,
  startIndex,
  player,
  onChecked,
}: {
  segments: TranscriptSegmentView[];
  languageCode: string;
  unspaced: boolean;
  startIndex: number;
  player: DictationPlayer;
  onChecked?: (check: DictationCheck) => void;
}) {
  const t = useT();
  const [phase, setPhase] = useState<Phase>("setup");
  const [level, setLevel] = useState<DictationLevel>("easy");
  const [speed, setSpeed] = useState(1);
  const [repeats, setRepeats] = useState(1);
  const [index, setIndex] = useState(Math.min(startIndex, Math.max(segments.length - 1, 0)));
  const [picked, setPicked] = useState<number[]>([]);
  const [typed, setTyped] = useState("");
  const [hint, setHint] = useState(false);
  const [diff, setDiff] = useState<DiffItem[]>([]);
  const [results, setResults] = useState<Record<number, Result>>({});
  const generation = useRef(0);

  const segment = segments[index];
  const tokens = useMemo(() => (segment ? dictationTokens(segment.text, unspaced) : []), [segment, unspaced]);
  const chips = useMemo(
    () => shuffledTokens(tokens.map((_, i) => String(i)), index + 1).map(Number),
    [tokens, index],
  );

  // Pause when the panel closes (switching mode or leaving the page), not on re-renders.
  const playerRef = useRef(player);
  playerRef.current = player;
  useEffect(() => () => playerRef.current.pause(), []);

  // Plays a sentence `times` times; a newer action (generation) cancels the rest.
  function playSentence(target: TranscriptSegmentView, times: number) {
    const run = ++generation.current;
    const play = (left: number) =>
      player.playClip(target.start_ms, target.end_ms, () => {
        if (run !== generation.current) return;
        if (left > 1) window.setTimeout(() => run === generation.current && play(left - 1), 400);
        else setPhase((current) => (current === "listening" ? "answering" : current));
      });
    play(times);
  }

  function listen() {
    if (!segment) return;
    setPhase((current) => (current === "checked" ? current : "listening"));
    playSentence(segment, 1);
  }

  function start() {
    player.setRate(speed);
    setResults({});
    goTo(index, true);
  }

  function goTo(next: number, autoplay: boolean) {
    generation.current++;
    player.pause();
    setIndex(next);
    setPicked([]);
    setTyped("");
    setHint(false);
    setDiff([]);
    setPhase("listening");
    const target = segments[next];
    if (autoplay && target) playSentence(target, repeats);
  }

  function check() {
    const answered = level === "easy" ? picked.map((i) => tokens[i]) : dictationTokens(typed, unspaced);
    const items = diffAnswer(tokens, answered);
    if (segment) {
      onChecked?.({
        segment_id: segment.segment_id,
        level,
        answer: level === "easy" ? answered.join(unspaced ? "" : " ") : typed,
        hint_shown: hint,
      });
    }
    setDiff(items);
    setResults((previous) => ({
      ...previous,
      [index]: { perfect: isPerfect(items), correct: correctCount(items), total: tokens.length },
    }));
    setPhase("checked");
  }

  function next() {
    if (index + 1 >= segments.length) {
      player.pause();
      setPhase("done");
      return;
    }
    goTo(index + 1, true);
  }

  if (segments.length === 0) {
    return <p className="muted"><T>This video has no sentences to write.</T></p>;
  }

  if (phase === "setup") {
    return (
      <div className="stack dictation-panel">
        <h2><T>Dictation</T></h2>
        <fieldset className="choice-row">
          <legend><T>Level</T></legend>
          <ChoiceButton active={level === "easy"} onClick={() => setLevel("easy")}><T>Easy · arrange the words</T></ChoiceButton>
          <ChoiceButton active={level === "hard"} onClick={() => setLevel("hard")}><T>Hard · type it</T></ChoiceButton>
        </fieldset>
        <fieldset className="choice-row">
          <legend><T>Speed</T></legend>
          {SPEEDS.map((value) => (
            <ChoiceButton key={value} active={speed === value} onClick={() => setSpeed(value)}>{value}×</ChoiceButton>
          ))}
        </fieldset>
        <fieldset className="choice-row">
          <legend><T>Hear each sentence</T></legend>
          {REPEATS.map((value) => (
            <ChoiceButton key={value} active={repeats === value} onClick={() => setRepeats(value)}>
              {value === 1 ? <T>once</T> : <T n={value}>{"{n} times"}</T>}
            </ChoiceButton>
          ))}
        </fieldset>
        <p className="muted small"><T>Starting from sentence</T> {index + 1} <T>of</T> {segments.length}.</p>
        <button type="button" className="dl-btn dl-btn--primary" onClick={start}><T>Start dictation</T></button>
      </div>
    );
  }

  if (phase === "done") {
    const done = Object.values(results);
    const perfect = done.filter((item) => item.perfect).length;
    const words = done.reduce((sum, item) => sum + item.correct, 0);
    const total = done.reduce((sum, item) => sum + item.total, 0);
    return (
      <div className="stack dictation-panel" aria-live="polite">
        <h2><T>Well done!</T></h2>
        <p>
          <T perfect={perfect} total={done.length} share={total ? Math.round((100 * words) / total) : 0}>{"{perfect} of {total} sentences perfect · {share}% of words right"}</T>
        </p>
        <div className="row">
          <button type="button" className="dl-btn dl-btn--primary" onClick={() => { setIndex(0); setPhase("setup"); }}>
            <T>Practise again</T>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="stack dictation-panel">
      <div className="row between">
        <span className="muted small"><T>Sentence</T> {index + 1} <T>of</T> {segments.length}</span>
        <div className="row">
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => goTo(index - 1, true)} disabled={index === 0}><T>Previous</T></button>
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => goTo(index + 1, true)} disabled={index >= segments.length - 1}><T>Skip</T></button>
        </div>
      </div>

      <div className="row">
        <button type="button" className="dl-btn dl-btn--secondary" onClick={listen} disabled={phase === "listening"}>
          {phase === "listening" ? <T>Listening…</T> : <T>Listen again</T>}
        </button>
        {level === "hard" && phase !== "checked" ? (
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => setHint((value) => !value)} aria-pressed={hint}>
            {hint ? <T>Hide hint</T> : <T>Show hint</T>}
          </button>
        ) : null}
      </div>

      {phase !== "checked" ? (
        level === "easy" ? (
          <div className="stack">
            <div className="chip-answer" aria-label={t("Your sentence")} lang={languageCode}>
              {picked.length === 0 ? <span className="muted small"><T>Tap the words in order</T></span> : null}
              {picked.map((tokenIndex, position) => (
                <button
                  key={`${tokenIndex}-${position}`}
                  type="button"
                  className="word-chip picked"
                  onClick={() => setPicked((current) => current.filter((_, i) => i !== position))}
                >
                  {tokens[tokenIndex]}
                </button>
              ))}
            </div>
            <div className="chip-pool" aria-label={t("Words")} lang={languageCode}>
              {chips.map((tokenIndex) =>
                picked.includes(tokenIndex) ? null : (
                  <button
                    key={tokenIndex}
                    type="button"
                    className="word-chip"
                    onClick={() => setPicked((current) => [...current, tokenIndex])}
                  >
                    {tokens[tokenIndex]}
                  </button>
                ),
              )}
            </div>
          </div>
        ) : (
          <div className="stack">
            {hint ? (
              <p className="dictation-hint" aria-label={t(unspaced ? "{n} characters" : "{n} words", { n: tokens.length })}>
                {lengthHint(tokens, unspaced).map((group, i) => (
                  <span key={i} className={unspaced ? "hint-char" : "hint-word"}>{group}</span>
                ))}
              </p>
            ) : null}
            <label htmlFor="dictation-typed" className="small muted"><T>Type what you hear</T></label>
            <textarea
              id="dictation-typed"
              rows={2}
              lang={languageCode}
              autoComplete="off"
              spellCheck={false}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              onKeyDown={(event) => {
                // Enter that ends an IME composition (pinyin, Vietnamese Telex) only commits the text.
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && typed.trim()) {
                  event.preventDefault();
                  check();
                }
              }}
            />
          </div>
        )
      ) : null}

      {phase !== "checked" ? (
        <button
          type="button"
          className="dl-btn dl-btn--primary"
          onClick={check}
          disabled={level === "easy" ? picked.length === 0 : !typed.trim()}
        >
          <T>Check</T>
        </button>
      ) : (
        <div className="stack" aria-live="polite">
          <p className={isPerfect(diff) ? "feedback correct" : "feedback incorrect"}>
            {isPerfect(diff) ? <T>Perfect!</T> : t(unspaced ? "{n} of {total} characters right" : "{n} of {total} words right", { n: correctCount(diff), total: tokens.length })}
          </p>
          <p className="dictation-diff" lang={languageCode}>
            {diff.map((item, i) => (
              <span key={i} className={`diff ${item.kind}`} title={item.kind}>
                {item.kind === "extra" ? item.answered : item.expected}
                {item.kind === "wrong" ? <small> ({item.answered})</small> : null}
                {unspaced ? "" : " "}
              </span>
            ))}
          </p>
          <p className="muted" lang={languageCode}>{segment.text}</p>
          {segment.translation ? (
            <p className="translation" lang={segment.translation.language_code}>{segment.translation.text}</p>
          ) : null}
          <button type="button" className="dl-btn dl-btn--primary" onClick={next}>
            {index + 1 >= segments.length ? <T>Finish</T> : <T>Next sentence</T>}
          </button>
        </div>
      )}
    </div>
  );
}

function ChoiceButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" className={active ? "choice active" : "choice"} aria-pressed={active} onClick={onClick}>
      {children}
    </button>
  );
}
