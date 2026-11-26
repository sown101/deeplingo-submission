import { useCallback, useEffect, useRef, useState } from "react";
import { useContainer } from "../../app/container";
import { tr } from "../../i18n/i18n";
import { ApiError } from "../../lib/api/errors";
import { MicrophoneError, startPcmRecorder, type PcmRecorder } from "../../lib/audio/pcmRecorder";
import { encodeWav, pcmDurationMs } from "../../lib/audio/wav";
import { speakingErrorMessage } from "../speaking/SpeakingFeedback";
import { newEventId, type AnswerResult } from "../review/reviewModels";

export type AttemptPhase = "idle" | "recording" | "assessing";

const MIN_ATTEMPT_MS = 300;
const MAX_ATTEMPT_MS = 8_000;

export interface AttemptWord { conceptId: string; languageCode: string; text: string }

/**
 * One saved word said aloud: record from the microphone, send the WAV to be assessed on the server, replay it. The
 * server keeps the result as the word's latest and logs it; it never moves the review schedule. `passId` ties an
 * attempt inside a review run to that run. Audio stays in memory.
 */
export function usePronunciationAttempt(passId: string | null = null) {
  const { review } = useContainer();
  const [phase, setPhase] = useState<AttemptPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [attemptUrl, setAttemptUrl] = useState<string | null>(null);

  const recorder = useRef<PcmRecorder | null>(null);
  const timer = useRef<number | null>(null);
  const generation = useRef(0);
  const starting = useRef(false);
  const replaying = useRef<HTMLAudioElement | null>(null);

  const release = useCallback(() => {
    generation.current += 1;
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    recorder.current?.dispose();
    recorder.current = null;
    replaying.current?.pause();
  }, []);

  useEffect(() => release, [release]);
  useEffect(() => () => { if (attemptUrl) URL.revokeObjectURL(attemptUrl); }, [attemptUrl]);

  /** Stops the microphone and forgets the attempt: for moving to another word or closing. */
  const reset = useCallback(() => {
    release();
    setPhase("idle");
    setError(null);
    setResult(null);
    setAttemptUrl(null);
  }, [release]);

  const stop = useCallback(async (word: AttemptWord) => {
    const active = recorder.current;
    if (!active) return;
    recorder.current = null;
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    const samples = active.stop();
    if (pcmDurationMs(samples) < MIN_ATTEMPT_MS) {
      setPhase("idle");
      setError(tr("That was too short. Say the whole word, then press Stop."));
      return;
    }
    const wav = encodeWav(samples);
    setAttemptUrl(URL.createObjectURL(wav));
    setPhase("assessing");
    const current = ++generation.current;
    try {
      const scored = await review.answerPronunciation(
        { clientEventId: newEventId(), passId, conceptId: word.conceptId, languageCode: word.languageCode }, wav);
      if (current === generation.current) setResult(scored);
    } catch (cause) {
      if (current === generation.current) setError(speakingErrorMessage(cause instanceof ApiError ? cause : null));
    } finally {
      if (current === generation.current) setPhase("idle");
    }
  }, [review, passId]);

  const start = useCallback(async (word: AttemptWord) => {
    if (starting.current || recorder.current) return;
    setError(null);
    setResult(null);
    setAttemptUrl(null);
    replaying.current?.pause();
    starting.current = true;
    const current = generation.current;
    try {
      const opened = await startPcmRecorder();
      if (current !== generation.current) {
        // Closed or moved on while the permission prompt was open.
        opened.dispose();
        return;
      }
      recorder.current = opened;
    } catch (cause) {
      setError(cause instanceof MicrophoneError && cause.kind === "denied"
        ? tr("Microphone access was blocked. Allow the microphone in your browser settings and try again.")
        : tr("No microphone is available in this browser."));
      return;
    } finally {
      starting.current = false;
    }
    setPhase("recording");
    timer.current = window.setTimeout(() => void stop(word), MAX_ATTEMPT_MS);
  }, [stop]);

  const replay = useCallback(() => {
    if (!attemptUrl) return;
    replaying.current?.pause();
    replaying.current = new Audio(attemptUrl);
    void replaying.current.play().catch(() => undefined);
  }, [attemptUrl]);

  return { phase, error, result, attemptUrl, start, stop, reset, replay };
}

export type PronunciationAttempt = ReturnType<typeof usePronunciationAttempt>;
