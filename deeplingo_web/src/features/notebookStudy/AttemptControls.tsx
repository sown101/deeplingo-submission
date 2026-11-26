import { Icon } from "../../design/notebookIcons";
import { T, useT } from "../../i18n/i18n";
import { PronunciationResult } from "./PronunciationResult";
import type { AttemptWord, PronunciationAttempt } from "./usePronunciationAttempt";

/** The microphone, the replay of the learner's own attempt, and the full result: the same in the dialog and in review. */
export function AttemptControls({ attempt, word }: { attempt: PronunciationAttempt; word: AttemptWord }) {
  const t = useT();
  const recording = attempt.phase === "recording";
  return <>
    {attempt.result?.assessment ? <PronunciationResult assessment={attempt.result.assessment} /> : null}
    {attempt.phase === "assessing" ? <p className="st-note" role="status"><T>Checking your pronunciation…</T></p> : null}
    {attempt.error ? <p className="st-error" role="alert">{attempt.error}</p> : null}
    <div className="st-mic-row">
      <button type="button" className={`st-mic${recording ? " rec" : ""}`} disabled={attempt.phase === "assessing"}
        aria-label={t(recording ? "Stop recording" : "Start recording")}
        onClick={() => void (recording ? attempt.stop(word) : attempt.start(word))}>
        <Icon name={recording ? "stop" : "mic"} />
      </button>
      <button type="button" className="nb-round" disabled={!attempt.attemptUrl || recording} aria-label={t("Replay your attempt")} onClick={attempt.replay}>
        <Icon name="play" />
      </button>
    </div>
  </>;
}
