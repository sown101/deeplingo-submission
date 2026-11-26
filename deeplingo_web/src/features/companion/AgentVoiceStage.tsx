import type { ReactNode } from "react";
import { Mascot } from "../../design/Mascot";
import { T, useT } from "../../i18n/i18n";
import type { MyWord } from "../words/wordsModels";

export type AgentVoicePhase = "idle" | "connecting" | "live" | "ended" | "failed";

export function AgentVoiceStage({ phase, paused, remaining, words, wordsLoading, wordsFailed,
  permissions, actions, feedback, error, canStart, helpLabel, onStart, onPause, onEnd, onHelp, onRetryWords,
  tools, utterance, hintWord, helping, helpCard, errorActions, choices, pronunciation }: {
  phase: AgentVoicePhase; paused: boolean; remaining: number | null;
  words: MyWord[]; wordsLoading: boolean; wordsFailed: boolean;
  permissions: ReactNode; actions?: ReactNode; feedback: ReactNode; error: string | null; canStart: boolean;
  helpLabel: string; tools: ReactNode;
  utterance: string | null;
  hintWord: string | null; helping: boolean; helpCard?: ReactNode; choices?: ReactNode; pronunciation?: ReactNode;
  errorActions?: ReactNode;
  onStart: () => void; onPause: () => void; onEnd: () => void; onHelp: () => void; onRetryWords: () => void;
}) {
  const t = useT();
  const live = phase === "live";
  const connecting = phase === "connecting";
  return <div className="realtime-screen agent-voice" data-phase={phase}>
    {live && remaining !== null ? <span className="agent-timer" aria-label={t("Time left")}>
      {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")}
    </span> : null}
    <div className="agent-stage">
      {!error ? <Mascot state={phase === "ended" ? "happy" : live && paused ? "sleepy" : live && helping ? "think" : live ? "listen" : "idle"} className={live || connecting ? "agent-stage-mascot session" : "agent-stage-mascot"} /> : null}
      {connecting ? <p className="agent-status" role="status"><T>Connecting to Tata…</T></p> : null}
      {live ? <div className="agent-status" aria-live="polite">
        <span>{paused ? t("Microphone paused") : helping ? t("Tata is giving a hint") : t("Listening to you")}</span>
        {!paused && !helping ? <span className="dl-wave" aria-hidden="true"><i /><i /><i /><i /></span> : null}
      </div> : null}
      {live && utterance ? <p className="agent-say" aria-live="polite">{utterance}</p> : null}
      {live ? pronunciation : null}
      {live ? choices : null}
      {live && helpCard ? <div className="agent-live-help">{helpCard}</div> : null}
      {error ? <section className="dl-card dl-state agent-stage-error" role="alert">
        <div className="dl-state__icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path fillRule="evenodd" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-1 5h2v7h-2zm0 9h2v2h-2z" /></svg></div>
        <h2 className="dl-state__title"><T>Voice could not start</T></h2>
        <p className="dl-state__body">{t(error)}</p>
        {canStart ? <button type="button" className="dl-btn dl-btn--secondary" onClick={onStart}><T>Retry</T></button> : null}
        {errorActions}
      </section> : null}
      {!connecting && !error && phase !== "ended" ? <div className="agent-words">
        {wordsLoading ? <div className="agent-chips" aria-label={t("Loading words…")}><span className="dl-skel" /><span className="dl-skel" /><span className="dl-skel" /></div>
          : wordsFailed ? <div className="agent-words-failure"><span><T>Your words could not be loaded.</T></span><button className="dl-btn dl-btn--secondary dl-btn--sm" onClick={onRetryWords}><T>Retry</T></button></div>
          : words.length ? <div className="agent-chips">{words.map(word => <span key={word.conceptId} lang={word.languageCode}
            className={`dl-chip dl-chip--${live && helping && word.text === hintWord ? "hint" : live && word.rung >= 4 ? "independent" : live && word.rung === 3 ? "assisted" : "todo"}`}>{word.text}</span>)}</div>
          : <p className="agent-empty-words"><T>Your notebook has no saved words yet. You can still talk freely.</T></p>}
      </div> : null}
      {actions}
      {feedback}
      {!live && !connecting ? permissions : null}
      {!live && !connecting && !error && canStart ? <button type="button" className="dl-btn dl-btn--primary dl-btn--lg dl-btn--block agent-start" onClick={onStart}>
        {phase === "idle" ? t("Start talking") : t("Start again")}
      </button> : null}
    </div>
    {live ? <div className="agent-live-tools">
      <button type="button" className="dl-btn dl-btn--primary dl-btn--sm" onClick={onHelp}>{helpLabel}</button>
      {tools}
    </div> : null}
    {live ? <div className="agent-session-controls">
      <button type="button" className="agent-mic" aria-label={paused ? t("Resume microphone") : t("Pause microphone")} aria-pressed={!paused} onClick={onPause}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-3.1A7 7 0 0 0 19 11z" /></svg>
      </button>
      <button type="button" className="dl-icon-btn" aria-label={t("End")} title={t("End")} onClick={onEnd}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
      </button>
    </div> : null}
  </div>;
}
