import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "../../design/notebookIcons";
import { T, useT } from "../../i18n/i18n";
import type { Answer, AnswerResult, Exercise, ReviewCard } from "../review/reviewModels";
import { AttemptControls } from "./AttemptControls";
import { joinParts } from "./studySession";
import { usePronunciationAttempt } from "./usePronunciationAttempt";

type Of<Type extends Exercise["type"]> = Extract<Exercise, { type: Type }>;

// The questions of a review. Each sends the learner's own input (the option they picked, the order they made, what
// they typed, their voice); the server grades it and the result marks the question.

export function ChoiceQuestion({ exercise, languageCode, reading, showAnswer, result, busy, imageSlot, onListen, onAnswer }: {
  exercise: Of<"choice"> | Of<"listening">; languageCode: string; reading: boolean; showAnswer: boolean; result: AnswerResult | null;
  busy: boolean; imageSlot: ReactNode; onListen: () => void; onAnswer: (answer: Answer) => void;
}) {
  const t = useT();
  const [picked, setPicked] = useState<string | null>(null);
  const listening = exercise.type === "listening";
  const tone = (option: string) => {
    if (!result) return picked === option ? " on" : "";
    if (option === picked) return result.correct ? " good" : " bad";
    return showAnswer && option === result.expected ? " good" : "";
  };
  return <>
    <div className="st-q-title">{listening ? <T>Listen and choose the word</T> : <T>Choose the meaning</T>}</div>
    {listening ? imageSlot : null}
    <div className="st-q-head">
      {exercise.type === "choice" ? <div className="st-q-word" lang={languageCode}>{exercise.text}</div> : null}
      <button type="button" className="nb-round" aria-label={t("Listen")} onClick={onListen}><Icon name="sound" /></button>
    </div>
    {exercise.type === "choice" && reading && exercise.reading ? <div className="st-reading">{exercise.reading}</div> : null}
    {exercise.type === "choice" && exercise.sentence ? <div className="st-reading" lang={languageCode}>{exercise.sentence}</div> : null}
    <div className="st-ans-col" role="group" aria-label={t(listening ? "Words" : "Meanings")}>
      {exercise.options.map((option) => (
        <button key={option} type="button" lang={listening ? languageCode : undefined} disabled={busy || !!result}
          className={`st-ans${tone(option)}`} onClick={() => { setPicked(option); onAnswer({ option }); }}>{option}</button>
      ))}
    </div>
    {!result ? <button type="button" className="nb-link" disabled={busy} onClick={() => { setPicked(null); onAnswer({ dont_know: true }); }}><T>I don't know</T></button> : null}
  </>;
}

/** A board of words and their meanings. Each pairing is sent as the meaning chosen for that word; the server says
 * whether it matches. The board is right when every word was matched at the first try. */
export function MatchQuestion({ cards, meanings, languageCode, onPair, onDone }: {
  cards: ReviewCard[]; meanings: string[]; languageCode: string;
  onPair: (card: ReviewCard, meaning: string) => Promise<AnswerResult | null>; onDone: (firstTry: boolean, missed: ReviewCard[]) => void;
}) {
  const t = useT();
  const [picked, setPicked] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, string>>({});
  const [missed, setMissed] = useState<ReviewCard[]>([]);
  const [wrong, setWrong] = useState(false);
  const [busy, setBusy] = useState(false);
  const finished = Object.keys(done).length === cards.length;

  async function choose(meaning: string) {
    const card = cards.find((item) => item.conceptId === picked);
    if (!card || busy) return;
    setBusy(true);
    const result = await onPair(card, meaning);
    setBusy(false);
    if (!result) return;
    setPicked(null);
    if (result.correct) {
      const next = { ...done, [card.conceptId]: meaning };
      setDone(next);
      setWrong(false);
      if (Object.keys(next).length === cards.length) onDone(missed.length === 0, missed);
    } else {
      setWrong(true);
      if (!missed.includes(card)) setMissed([...missed, card]);
    }
  }
  const usedMeanings = new Set(Object.values(done));
  return <>
    <div className="st-q-title"><T>Match each word with its meaning</T></div>
    <div className="st-ans-grid">
      <div className="st-ans-col" role="group" aria-label={t("Words")}>
        {cards.map((card) => (
          <button key={card.conceptId} type="button" lang={languageCode} disabled={finished || busy || card.conceptId in done} aria-pressed={picked === card.conceptId}
            className={`st-ans${card.conceptId in done ? " good" : ""}${picked === card.conceptId ? " on" : ""}`}
            onClick={() => { setPicked(card.conceptId); setWrong(false); }}>{card.text}</button>
        ))}
      </div>
      <div className="st-ans-col" role="group" aria-label={t("Meanings")}>
        {meanings.map((meaning, index) => (
          <button key={`${meaning}-${index}`} type="button" disabled={finished || busy || !picked || usedMeanings.has(meaning)}
            className={`st-ans${usedMeanings.has(meaning) ? " good" : ""}`} onClick={() => void choose(meaning)}>{meaning}</button>
        ))}
      </div>
    </div>
    {wrong ? <p className="st-note" role="status"><T>Those two do not match. Try again.</T></p> : null}
  </>;
}

interface Chip { key: number; text: string }

export function OrderQuestion({ exercise, languageCode, locked, onReady }: {
  exercise: Of<"order">; languageCode: string; locked: boolean; onReady: (answer: Answer | null) => void;
}) {
  const [placed, setPlaced] = useState<Chip[]>([]);
  const [bank, setBank] = useState<Chip[]>(() => exercise.parts.map((text, key) => ({ key, text })));

  function update(nextPlaced: Chip[], nextBank: Chip[]) {
    setPlaced(nextPlaced);
    setBank(nextBank);
    onReady(nextBank.length === 0 ? { text: joinParts(nextPlaced.map((chip) => chip.text), languageCode) } : null);
  }
  return <>
    <div className="st-q-title">{exercise.kind === "sentence" ? <T>Put the sentence in order</T> : <T>Put the characters in order</T>}</div>
    {exercise.meaning ? <div className="st-reading">{exercise.meaning}</div> : null}
    <div className="st-dropzone" data-testid="order-placed">
      {placed.map((chip) => (
        <button key={chip.key} type="button" className="nb-chip" lang={languageCode} disabled={locked} onClick={() => update(placed.filter((item) => item !== chip), [...bank, chip])}>{chip.text}</button>
      ))}
    </div>
    <div className="nb-chips st-wrap" data-testid="order-bank">
      {bank.map((chip) => (
        <button key={chip.key} type="button" className="nb-chip" lang={languageCode} disabled={locked} onClick={() => update([...placed, chip], bank.filter((item) => item !== chip))}>{chip.text}</button>
      ))}
    </div>
  </>;
}

export function WriteQuestion({ exercise, languageCode, reading, locked, imageSlot, onListen, onReady }: {
  exercise: Of<"writing">; languageCode: string; reading: boolean; locked: boolean; imageSlot: ReactNode; onListen: () => void;
  onReady: (answer: Answer | null) => void;
}) {
  const t = useT();
  const [typed, setTyped] = useState("");
  const cue = exercise.meaning ?? exercise.reading;
  return <>
    <div className="st-q-title"><T>Write the word with this meaning</T></div>
    {imageSlot}
    <div className="st-q-head">
      <div>{cue}</div>
      <button type="button" className="nb-round" aria-label={t("Listen")} onClick={onListen}><Icon name="sound" /></button>
    </div>
    {reading && exercise.reading && exercise.meaning ? <div className="st-reading">{exercise.reading}</div> : null}
    <input className="nb-input" autoFocus value={typed} disabled={locked} placeholder={t("Type the word")} aria-label={t("Type the word")} lang={languageCode}
      onChange={(event) => { setTyped(event.target.value); onReady(event.target.value.trim() ? { text: event.target.value.trim() } : null); }} />
  </>;
}

export function SpeakQuestion({ card, exercise, languageCode, reading, passId, imageSlot, onListen, onScored }: {
  card: ReviewCard; exercise: Of<"pronunciation">; languageCode: string; reading: boolean; passId: string; imageSlot: ReactNode;
  onListen: () => void; onScored: (result: AnswerResult) => void;
}) {
  const t = useT();
  const attempt = usePronunciationAttempt(passId);
  const { result } = attempt;
  useEffect(() => {
    if (result) onScored(result);
    // A new score is the only event here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);
  return <>
    <div className="st-q-title"><T>Say this word out loud</T></div>
    {imageSlot}
    <div className="st-q-head">
      <div className="st-q-word" lang={languageCode}>{exercise.text}</div>
      <button type="button" className="nb-round" aria-label={t("Listen")} onClick={onListen}><Icon name="sound" /></button>
    </div>
    {reading && exercise.reading ? <div className="st-reading">{exercise.reading}</div> : null}
    {exercise.meaning ? <div>{exercise.meaning}</div> : null}
    <AttemptControls attempt={attempt} word={{ conceptId: card.conceptId, languageCode, text: exercise.text }} />
  </>;
}
