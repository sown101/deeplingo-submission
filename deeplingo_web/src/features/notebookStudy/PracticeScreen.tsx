import { useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { Icon } from "../../design/notebookIcons";
import { Mascot } from "../../design/Mascot";
import { T, useT } from "../../i18n/i18n";
import { newEventId, newPassId, type Answer, type AnswerResult, type ReviewCard } from "../review/reviewModels";
import { ChoiceQuestion, MatchQuestion, OrderQuestion, SpeakQuestion, WriteQuestion } from "./practiceQuestions";
import { SpeedSlider, StudyHeader, StudyMessage, StudySwitch } from "./StudyParts";
import { readReviewParams, reviewItems, serverTypes, type StudyDisplay } from "./studySession";

const MAX_IMAGES = 24;

/**
 * The notebook's Review for one language's deck: the chosen words, or the deck's due cards. The
 * server builds each question from the chosen types and grades every answer; Multiple choice, Match pairs and Order
 * move a card's review schedule once per review, Pronunciation and Writing are practice only.
 */
export function PracticeScreen() {
  const { language = "" } = useParams();
  const [params] = useSearchParams();
  const setup = useMemo(() => readReviewParams(params), [params]);
  const [round, setRound] = useState(0);
  return <PracticeRun key={`${round}:${params}`} language={language} setup={setup} onAgain={() => setRound(round + 1)} />;
}

interface Outcome { card: ReviewCard; right: boolean; skipped: boolean }
type Setup = ReturnType<typeof readReviewParams>;

function PracticeRun({ language, setup, onAgain }: { language: string; setup: Setup; onAgain: () => void }) {
  const t = useT();
  const { review, notebook } = useContainer();
  const [passId] = useState(newPassId);
  const [display, setDisplay] = useState<StudyDisplay>(setup.display);
  const [speed, setSpeed] = useState(1);
  const [index, setIndex] = useState(0);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [ready, setReady] = useState<Answer | null>(null);
  const [boardDone, setBoardDone] = useState<{ firstTry: boolean; missed: ReviewCard[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [audioFailed, setAudioFailed] = useState(false);
  const shownAt = useRef(performance.now());
  const player = useRef<HTMLAudioElement | null>(null);

  const due = useQuery({
    queryKey: ["review-run", language, setup.types.join(","), setup.conceptIds.join(","), passId],
    queryFn: () => review.due(language, serverTypes(setup.types), setup.conceptIds),
    staleTime: Infinity, refetchOnWindowFocus: false, retry: false,
  });
  const items = useMemo(() => (due.data ? reviewItems(due.data.cards) : null), [due.data]);
  const imageIds = [...new Set((due.data?.cards ?? []).filter((card) => ["listening", "writing", "pronunciation"].includes(card.exercise.type))
    .map((card) => card.conceptId))].slice(0, MAX_IMAGES);
  const images = useQuery({
    queryKey: ["notebook-study-images", imageIds],
    queryFn: () => notebook.images(imageIds),
    enabled: display.images && imageIds.length > 0,
    retry: false,
  }).data;

  const options = <>
    <StudySwitch label={t("Show the answer right away")} on={display.showAnswer} onToggle={() => setDisplay({ ...display, showAnswer: !display.showAnswer })} />
    <StudySwitch label={t("Images")} on={display.images} onToggle={() => setDisplay({ ...display, images: !display.images })} />
    <StudySwitch label={t("Show reading")} on={display.reading} onToggle={() => setDisplay({ ...display, reading: !display.reading })} />
    <div className="nb-sep" />
    <SpeedSlider speed={speed} onChange={setSpeed} />
  </>;
  const shell = (body: React.ReactNode) => <div className="st-page"><StudyHeader back={setup.back} title={t("Review")} options={options} />{body}</div>;

  if (due.isError) {
    return shell(<StudyMessage>
      <p role="alert"><T>Your cards could not be loaded.</T></p>
      <button type="button" className="nb-btn main" onClick={() => void due.refetch()}><T>Retry</T></button>
    </StudyMessage>);
  }
  if (!items) return shell(<StudyMessage><p role="status"><T>Getting your questions ready…</T></p></StudyMessage>);
  if (items.length === 0) {
    return shell(<StudyMessage>
      <Mascot state="sleepy" className="st-summary-mascot" />
      <p><T>Nothing to review this way right now.</T></p>
      <Link className="nb-btn main" to={setup.back}><T>Back to notebook</T></Link>
    </StudyMessage>);
  }

  const item = items[index];
  if (!item) {
    const graded = outcomes.filter((outcome) => !outcome.skipped);
    const good = graded.filter((outcome) => outcome.right).length;
    const missed = [...new Map(graded.filter((outcome) => !outcome.right).map((outcome) => [outcome.card.conceptId, outcome.card])).values()];
    return shell(<StudyMessage>
      <Mascot state="happy" className="st-summary-mascot" />
      <b className="st-summary-score">{good}/{graded.length}</b>
      <p><T>You finished this review.</T></p>
      {setup.types.some((type) => type === "speak" || type === "write")
        ? <p className="st-note"><T>Pronunciation and writing are practice: they do not change your review schedule.</T></p> : null}
      {missed.length ? <div className="st-missed">
        <span className="st-note"><T>Worth another look</T></span>
        <div className="nb-chips st-wrap">{missed.map((card) => <span key={card.conceptId} className="nb-chip st-static" lang={language}>{card.text}</span>)}</div>
      </div> : null}
      <div className="st-summary-actions">
        <Link className="nb-btn" to={setup.back}><T>Back to notebook</T></Link>
        <button type="button" className="nb-btn main" onClick={onAgain}><T>Practise again</T></button>
      </div>
    </StudyMessage>);
  }

  async function play(conceptId: string) {
    setAudioFailed(false);
    try {
      const url = await review.audioUrl(conceptId);
      player.current?.pause();
      player.current = new Audio(url);
      player.current.playbackRate = speed;
      await player.current.play();
    } catch {
      setAudioFailed(true);
    }
  }

  async function send(card: ReviewCard, answer: Answer, exerciseType: "choice" | "listening" | "match" | "order" | "writing"): Promise<AnswerResult | null> {
    setBusy(true);
    setFailed(false);
    try {
      return await review.answer({
        clientEventId: newEventId(), passId, conceptId: card.conceptId, languageCode: language, exerciseType, answer,
        hintUsed: false, responseMs: Math.round(performance.now() - shownAt.current),
      });
    } catch {
      setFailed(true);
      return null;
    } finally {
      setBusy(false);
    }
  }

  function next(outcome: Outcome[]) {
    setOutcomes([...outcomes, ...outcome]);
    setResult(null);
    setReady(null);
    setBoardDone(null);
    setFailed(false);
    setAudioFailed(false);
    setIndex(index + 1);
    shownAt.current = performance.now();
  }

  const imageFor = (conceptId: string) => {
    const image = display.images ? images?.find((entry) => entry.conceptId === conceptId) : undefined;
    return image ? (
      <figure className="st-q-image">
        <img src={image.thumbnailUrl ?? image.imageUrl} alt="" />
        {image.creator || image.license ? <figcaption>{[image.creator, image.license].filter(Boolean).join(" · ")}</figcaption> : null}
      </figure>
    ) : null;
  };

  const progress = `${Math.round((index / items.length) * 100)}%`;
  const header = <div className="st-progress">
    <span><i style={{ width: progress }} /></span>
    <span>{index + 1}/{items.length}</span>
  </div>;

  if (item.kind === "match") {
    return shell(<div className="st-card">
      {header}
      <MatchQuestion key={item.id} cards={item.cards} meanings={item.meanings} languageCode={language}
        onPair={(card, meaning) => send(card, { option: meaning }, "match")}
        onDone={(firstTry, missed) => setBoardDone({ firstTry, missed })} />
      {failed ? <p className="st-error" role="alert"><T>The answer was not received. Try again.</T></p> : null}
      <button type="button" className={`nb-btn wide${boardDone ? " main" : ""}`} disabled={!boardDone}
        onClick={() => next(item.cards.map((card) => ({ card, right: !boardDone?.missed.includes(card), skipped: false })))}>{t("Continue")}</button>
    </div>);
  }

  const card = item.card;
  const exercise = card.exercise;
  const say = () => void play(card.conceptId);
  const isSpeak = exercise.type === "pronunciation";
  const typed = exercise.type === "order" || exercise.type === "writing";

  async function check(event?: FormEvent) {
    event?.preventDefault();
    if (result) { next([{ card, right: result.correct, skipped: false }]); return; }
    if (isSpeak) { next([{ card, right: false, skipped: true }]); return; }
    if (!ready || busy || !typed) return;
    const graded = await send(card, ready, exercise.type as "order" | "writing");
    if (graded) setResult(graded);
  }
  async function pick(answer: Answer) {
    if (exercise.type !== "choice" && exercise.type !== "listening") return;
    const graded = await send(card, answer, exercise.type);
    if (graded) setResult(graded);
  }

  const buttonLabel = result ? "Continue" : isSpeak ? "Skip" : typed ? "Check" : null;
  return shell(
    <form className="st-card" onSubmit={(event) => void check(event)}>
      {header}
      {exercise.type === "choice" || exercise.type === "listening"
        ? <ChoiceQuestion key={item.id} exercise={exercise} languageCode={language} reading={display.reading} showAnswer={display.showAnswer}
            result={result} busy={busy} imageSlot={imageFor(card.conceptId)} onListen={say} onAnswer={(answer) => void pick(answer)} />
        : exercise.type === "order"
          ? <OrderQuestion key={item.id} exercise={exercise} languageCode={language} locked={!!result || busy} onReady={setReady} />
          : exercise.type === "writing"
            ? <WriteQuestion key={item.id} exercise={exercise} languageCode={language} reading={display.reading} locked={!!result || busy}
                imageSlot={imageFor(card.conceptId)} onListen={say} onReady={setReady} />
            : exercise.type === "pronunciation"
              ? <SpeakQuestion key={item.id} card={card} exercise={exercise} languageCode={language} reading={display.reading} passId={passId}
                  imageSlot={imageFor(card.conceptId)} onListen={say} onScored={setResult} />
              : null}
      {result && !isSpeak ? (
        <div className={`st-fb ${result.correct ? "good" : "bad"}`} role="status">
          <span>{result.correct ? <T>Correct</T> : display.showAnswer ? <T answer={result.expected}>{"Not quite · Answer: {answer}"}</T> : <T>Not quite</T>}</span>
          <button type="button" aria-label={t("Listen")} onClick={say}><Icon name="sound" /></button>
        </div>
      ) : null}
      {failed ? <p className="st-error" role="alert"><T>The answer was not received. Try again.</T></p> : null}
      {audioFailed ? <p className="st-note" role="status"><T>Audio is not available for this word.</T></p> : null}
      {buttonLabel ? <button className={`nb-btn wide${result || ready ? " main" : ""}`} disabled={busy || (buttonLabel === "Check" && !ready)}>{t(buttonLabel)}</button> : null}
    </form>,
  );
}
