import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import type { TranscriptSegmentView } from "../../../lib/api/dto";
import type { QuestionAnswer, RegionQuestion } from "./questionModels";
import { T } from "../../../i18n/i18n";

// While the part is being prepared on the server, read again shortly.
const PREPARING_POLL_MS = 5_000;

// M1 S6: a few comprehension questions about the study part. The server checks each answer and
// shows where the answer is in the video. Practice only: answers never change scores or reviews.
export function QuestionsPanel({
  libraryItemId,
  regionKey,
  segments,
  languageCode,
  onPlaySentence,
}: {
  libraryItemId: string;
  // Changes when the learner chooses another part (or its preparation moves on).
  regionKey: string;
  segments: TranscriptSegmentView[];
  languageCode: string;
  onPlaySentence: (segment: TranscriptSegmentView) => void;
}) {
  const { playback } = useContainer();
  const query = useQuery({
    queryKey: ["region-questions", libraryItemId, regionKey],
    queryFn: () => playback.getRegionQuestions(libraryItemId),
    retry: false,
    staleTime: 0,
    refetchInterval: (state) => (state.state.data?.status === "preparing" ? PREPARING_POLL_MS : false),
  });

  if (query.isPending) return <p role="status"><T>Loading questions…</T></p>;
  if (query.isError) {
    return (
      <div className="workspace-card" role="alert">
        <p><T>We could not load the questions.</T></p>
        <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => query.refetch()}>
          <T>Try again</T>
        </button>
      </div>
    );
  }
  const view = query.data;
  const note = {
    no_region: "Choose a study part in the transcript to get a few questions about it.",
    not_prepared: "Questions come once this part is prepared. You can still watch and practise.",
    preparing: "Questions for this part are being prepared…",
    none: "There are no questions for this part. Try Dictation or Shadowing instead.",
    unavailable: "Questions are not available for this part right now.",
    ready: null,
  }[view.status];

  return (
    <div className="stack workspace-card questions-panel">
      <h2><T>Questions</T></h2>
      {note ? (
        <p className="muted" role="status">
          <T>{note}</T>
        </p>
      ) : (
        <>
          {view.questions.map((question, index) => (
            <QuestionCard
              key={question.id}
              number={index + 1}
              question={question}
              libraryItemId={libraryItemId}
              segments={segments}
              languageCode={languageCode}
              onPlaySentence={onPlaySentence}
            />
          ))}
        </>
      )}
    </div>
  );
}

function QuestionCard({
  number,
  question,
  libraryItemId,
  segments,
  languageCode,
  onPlaySentence,
}: {
  number: number;
  question: RegionQuestion;
  libraryItemId: string;
  segments: TranscriptSegmentView[];
  languageCode: string;
  onPlaySentence: (segment: TranscriptSegmentView) => void;
}) {
  const { playback } = useContainer();
  const [selected, setSelected] = useState<number | null>(null);
  const [answer, setAnswer] = useState<QuestionAnswer | null>(null);
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(false);
  // One event ID per chosen option: resending after a failure is stored once.
  const eventIds = useRef(new Map<number, string>());

  async function choose(index: number) {
    if (answer || sending) return;
    setSelected(index);
    setSending(true);
    setFailed(false);
    let id = eventIds.current.get(index);
    if (!id) {
      id = crypto.randomUUID();
      eventIds.current.set(index, id);
    }
    try {
      setAnswer(await playback.answerRegionQuestion(libraryItemId, question.id, { id, selected_option: index }));
    } catch {
      setFailed(true);
    } finally {
      setSending(false);
    }
  }

  const evidence = answer ? segments.find((segment) => segment.segment_id === answer.evidence_segment_id) : undefined;
  const optionClass = (index: number) => {
    if (!answer) return selected === index ? "option selected" : "option";
    if (index === answer.correct_index) return "option correct";
    return index === answer.selected_option ? "option wrong" : "option";
  };

  return (
    <fieldset className="question-card stack" aria-busy={sending}>
      <legend>
        {number}. {question.question}
      </legend>
      <div className="question-options">
        {question.options.map((text, index) => (
          <button
            key={index}
            type="button"
            className={optionClass(index)}
            aria-pressed={selected === index}
            disabled={answer !== null || sending}
            onClick={() => void choose(index)}
          >
            {text}
          </button>
        ))}
      </div>
      {failed ? (
        <p className="region-error" role="alert">
          <T>We could not check your answer. Choose again to retry.</T>
        </p>
      ) : null}
      {answer ? (
        <div className="question-result" role="status">
          <p className={answer.correct ? "result-right" : "result-wrong"}>
            {answer.correct ? <T>Right.</T> : `Not quite. The answer is “${question.options[answer.correct_index]}”.`}
          </p>
          <p>
            <span className="muted small"><T>In the video:</T> </span>
            <q lang={languageCode}>{answer.evidence_quote}</q>
          </p>
          <p className="muted small">{answer.explanation}</p>
          {evidence ? (
            <button type="button" className="dl-btn dl-btn--plain dl-btn--sm" onClick={() => onPlaySentence(evidence)}>
              <T>Play this sentence</T>
            </button>
          ) : null}
        </div>
      ) : null}
    </fieldset>
  );
}
