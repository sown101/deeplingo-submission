import { useState, type CSSProperties, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { Mascot } from "../../design/Mascot";
import { T, useT } from "../../i18n/i18n";
import { newEventId, type GrammarExercise, type GrammarGrade, type GrammarPoint } from "../review/reviewModels";
import "../review/review.css";

// The notebook's Grammar tab, laid out like the shelf: the level and progress on the left, the "redo" list and the
// grammar points by topic on the right. A point's lesson and its exercises open in the right column; the server grades
// every answer and keeps the result per point (no FSRS). A correct answer closes the agent's "redo" request.
export function GrammarShelf({ toggle, language }: { toggle: ReactNode; language: string | null }) {
  const t = useT();
  const { review } = useContainer();
  const queryClient = useQueryClient();
  const [level, setLevel] = useState<string | undefined>();
  const [open, setOpen] = useState<GrammarPoint | null>(null);
  const [practice, setPractice] = useState<{ title: string; exercises: GrammarExercise[] } | null>(null);
  const overview = useQuery({
    queryKey: ["grammar", language, level ?? ""], enabled: !!language, retry: false,
    queryFn: () => review.grammar(language as string, level),
  });
  const data = overview.data;
  const points = data?.points ?? [];
  const tried = (point: GrammarPoint) => point.attempts > 0;
  const practised = points.filter(tried).length;
  const correct = points.reduce((sum, point) => sum + point.correctCount, 0);
  const wrong = points.reduce((sum, point) => sum + point.incorrectCount, 0);
  const share = points.length ? practised / points.length : 0;
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["grammar", language] });

  const start = useMutation({
    mutationFn: async (scope: { title: string; grammarKey?: string }) => ({
      title: scope.title,
      exercises: await review.grammarExercises(language as string, scope.grammarKey ? { grammarKey: scope.grammarKey } : { level: data?.level ?? undefined }),
    }),
    onSuccess: (value) => { setOpen(null); setPractice(value); },
  });
  const learned = useMutation({
    mutationFn: (point: GrammarPoint) => review.grammarLessonLearned(language as string, point.key, newEventId()),
    onSuccess: refresh,
  });

  function backToPoints() {
    setPractice(null);
    setOpen(null);
    refresh();
  }
  const back = <button type="button" className="shelf-more" onClick={backToPoints}><T>Back to grammar points</T></button>;

  return <div className="shelf-grid">
    <div className="shelf-col">
      {toggle}
      <section className="shelf-card gram-summary" aria-labelledby="gram-title">
        <div className="shelf-chart-head">
          <h2 id="gram-title" className="shelf-chart-title"><T>Grammar</T>{data?.level ? <> <em>{data.level}</em></> : null}</h2>
        </div>
        {data?.levels.length ? <div className="gram-levels" role="group" aria-label={t("Level")}>
          {data.levels.map((value) => <button key={value} type="button" aria-pressed={data.level === value} onClick={() => { backToPoints(); setLevel(value); }}>{value}</button>)}
        </div> : null}
        <div className="shelf-donut">
          <div className="shelf-ring" style={{ background: `conic-gradient(var(--blue-strong) 0 ${share * 360}deg, var(--nb-tile) ${share * 360}deg 360deg)` }}>
            <div>{practised}/{points.length}<small><T>points</T></small></div>
          </div>
          <div className="shelf-legend">
            <div><b data-tone="can-use">{correct}</b>{t("Correct answers")}</div>
            <div><b data-tone="learning">{wrong}</b>{t("Wrong answers")}</div>
            <div><b data-tone="known">{points.length - practised}</b>{t("Not practised yet")}</div>
          </div>
        </div>
        <button type="button" className="shelf-due" disabled={!points.length || start.isPending}
          onClick={() => start.mutate({ title: `${t("Practice")} · ${data?.level ?? ""}` })}>
          <T>Practise now</T>
          <Mascot state="happy" />
        </button>
        {start.isError ? <p className="error" role="alert"><T>The questions could not be loaded. Please try again.</T></p> : null}
      </section>
    </div>

    <div className="shelf-col">
      {overview.isPending && language ? <p role="status"><T>Loading…</T></p> : null}
      {overview.isError ? <div role="alert" className="shelf-card">
        <p className="error"><T>The practice could not be loaded.</T></p>
        <button type="button" className="nb-btn" onClick={() => void overview.refetch()}><T>Retry</T></button>
      </div> : null}
      {data && data.levels.length === 0 ? <div className="shelf-card shelf-empty"><Mascot state="listen" /><p><T>Content for your language is being prepared.</T></p></div> : null}

      {practice ? <section className="shelf-card shelf-sec gram-practice" aria-label={t("Grammar exercises")}>
        <div className="shelf-sec-head"><h2 className="shelf-title">{practice.title}</h2>{back}</div>
        <GrammarExercises language={language as string} exercises={practice.exercises} onAnswered={refresh} onDone={backToPoints} />
      </section> : open ? <section className="shelf-card shelf-sec gram-lesson" aria-labelledby="gram-lesson-title">
        <div className="shelf-sec-head"><h2 id="gram-lesson-title" className="shelf-title">{open.title}</h2>{back}</div>
        {open.lesson ? <>
          <p>{open.lesson.summary}</p>
          <h3><T>Rules</T></h3>
          <ul>{open.lesson.rules.map((rule) => <li key={rule}>{rule}</li>)}</ul>
          <h3><T>Examples</T></h3>
          <ul className="gram-examples">{open.lesson.examples.map((example) => <li key={example.text}><b>{example.text}</b><span>{example.meaning}</span></li>)}</ul>
          {open.lesson.mistakes?.length ? <>
            <h3><T>Common mistakes</T></h3>
            <ul>{open.lesson.mistakes.map((mistake) => <li key={mistake.wrong}><s>{mistake.wrong}</s> → <strong>{mistake.right}</strong> <span className="shelf-muted">{mistake.why}</span></li>)}</ul>
          </> : null}
        </> : <p className="shelf-muted"><T>This point has no lesson yet.</T></p>}
        <div className="rv-row">
          {open.lesson ? <button type="button" className="nb-btn" disabled={!!open.lessonLearnedAt || learned.isPending || learned.isSuccess}
            onClick={() => learned.mutate(open)}>{open.lessonLearnedAt || learned.isSuccess ? <T>Lesson learned</T> : <T>Mark the lesson as learned</T>}</button> : null}
          <button type="button" className="nb-btn main" disabled={start.isPending} onClick={() => start.mutate({ title: open.title, grammarKey: open.key })}><T>Practise this point</T></button>
        </div>
      </section> : <>
        {data?.redo.length ? <section className="shelf-card shelf-sec" aria-labelledby="gram-redo">
          <div className="shelf-sec-head"><h2 id="gram-redo" className="shelf-title"><T>To redo</T></h2><span className="gram-count">{data.redo.length}</span></div>
          <ul className="rv-redo">
            {data.redo.map((item) => <li key={item.requestId}>
              <span><strong>{item.title}</strong>{item.reason ? <><br /><small>{item.reason}</small></> : null}</span>
              <button type="button" className="nb-btn main" disabled={start.isPending} onClick={() => start.mutate({ title: item.title, grammarKey: item.grammarKey })}><T>Redo</T></button>
            </li>)}
          </ul>
        </section> : null}
        {(data?.topics ?? []).map((topic) => {
          const inTopic = points.filter((point) => point.topicKey === topic.key);
          if (!inTopic.length) return null;
          return <section key={topic.key} className="shelf-card shelf-sec" aria-labelledby={`gram-${topic.key}`}>
            <div className="shelf-sec-head">
              <h2 id={`gram-${topic.key}`} className="shelf-title">{topic.title}</h2>
              <span className="gram-count">{inTopic.filter(tried).length}/{inTopic.length}</span>
            </div>
            <ul className="gram-tiles">
              {inTopic.map((point) => <li key={point.key}>
                <button type="button" className={`shelf-tile gram-tile${tried(point) ? " done" : ""}`} onClick={() => setOpen(point)}>
                  <strong>{point.title}</strong>
                  <small>{tried(point) ? t("{correct} correct, {wrong} wrong", { correct: point.correctCount, wrong: point.incorrectCount }) : t("Not practised yet")}</small>
                  <i aria-hidden="true" style={{ "--gram-right": tried(point) ? point.correctCount / point.attempts : 0 } as CSSProperties} />
                </button>
              </li>)}
            </ul>
          </section>;
        })}
      </>}
    </div>
  </div>;
}

function GrammarExercises({ language, exercises, onAnswered, onDone }: {
  language: string; exercises: GrammarExercise[]; onAnswered: () => void; onDone: () => void;
}) {
  const t = useT();
  const { review } = useContainer();
  const [index, setIndex] = useState(0);
  const [choice, setChoice] = useState("");
  const [eventId, setEventId] = useState(newEventId);
  const [grade, setGrade] = useState<GrammarGrade | null>(null);
  const exercise = exercises[index];
  const answer = useMutation({
    mutationFn: () => review.grammarAnswer(language, exercise, choice, eventId),
    onSuccess: (value) => { setGrade(value); onAnswered(); },
  });
  function next() { setIndex((value) => value + 1); setChoice(""); setGrade(null); setEventId(newEventId()); answer.reset(); }
  if (!exercise) {
    return <div role="status" className="stack"><p><T>Practice round complete.</T></p>
      <button type="button" className="dl-btn dl-btn--secondary" onClick={onDone}><T>Choose another set</T></button></div>;
  }
  return <div className="card stack grammar-question">
    <p className="small muted">{t("Question {n}/{total}", { n: index + 1, total: exercises.length })}</p>
    <p>{exercise.prompt}</p>
    <fieldset className="grammar-options" disabled={answer.isPending || !!grade}><legend>{t("Choose an answer")}</legend>
      {exercise.options.map((option) => <label key={option.id} className="grammar-option"
        data-result={grade ? option.id === grade.correctOptionId ? "correct" : option.id === choice ? "incorrect" : undefined : undefined}>
        <input type="radio" name="grammar-choice" value={option.id} checked={choice === option.id} onChange={() => setChoice(option.id)} />{option.text}
      </label>)}
    </fieldset>
    {!grade ? <button type="button" className="dl-btn dl-btn--primary" disabled={!choice || answer.isPending} onClick={() => answer.mutate()}>{t("Check")}</button> : null}
    {answer.isError ? <p role="alert">{t("The result was not received. Press Check to send it again.")}</p> : null}
    {grade ? <div role="status" className="stack grammar-feedback"><strong>{grade.correct ? t("Correct") : t("Not quite")}</strong>
      <p>{t("Answer: {answer}", { answer: exercise.options.find((option) => option.id === grade.correctOptionId)?.text ?? "" })}</p>
      <p>{grade.explanation}</p>
      {grade.redoClosed ? <p><T>Removed from your redo list.</T></p> : null}
      <button type="button" className="dl-btn dl-btn--primary" onClick={next}>{t("Next question")}</button></div> : null}
  </div>;
}
