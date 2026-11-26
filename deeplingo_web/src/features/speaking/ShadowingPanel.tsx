import { useCallback, useEffect, useRef, useState } from "react";
import { useContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { MicrophoneError, startPcmRecorder, type PcmRecorder } from "../../lib/audio/pcmRecorder";
import { encodeWav, pcmDurationMs } from "../../lib/audio/wav";
import type { TranscriptSegmentView } from "../../lib/api/dto";
import type { ShadowingAssessment } from "./speakingModels";
import { BAND_COPY, ScoreBars, ScoreRing, WordFeedback, speakingErrorMessage } from "./SpeakingFeedback";
import { T, useT, tr } from "../../i18n/i18n";

type Phase = "idle" | "recording" | "assessing";

const MIN_ATTEMPT_MS = 400;

export interface ShadowingPlayer {
  playClip: (startMs: number, endMs: number, onEnd?: () => void) => void;
  pause: () => void;
}

/** Sentences short enough to shadow (the backend assesses at most about 30 s). */
export function shadowingSegments(segments: TranscriptSegmentView[]): TranscriptSegmentView[] {
  return segments.filter((segment) => segment.end_ms - segment.start_ms <= 30_000 && segment.text.trim());
}

// Shadowing beside the video (non-evidential): listen to one sentence on the
// page's player, record yourself, and read the server's pronunciation feedback.
export function ShadowingPanel({
  libraryItemId,
  regionId,
  segments,
  languageCode,
  startIndex,
  player,
}: {
  libraryItemId: string;
  regionId?: string;
  segments: TranscriptSegmentView[];
  languageCode: string;
  startIndex: number;
  player: ShadowingPlayer;
}) {
  const t = useT();
  const { speaking } = useContainer();
  const [index, setIndex] = useState(Math.min(startIndex, Math.max(segments.length - 1, 0)));
  const [phase, setPhase] = useState<Phase>("idle");
  const [listening, setListening] = useState(false);
  const [level, setLevel] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [showTranslation, setShowTranslation] = useState(false);
  const [results, setResults] = useState<Record<string, ShadowingAssessment>>({});
  const [recordingUrl, setRecordingUrl] = useState<string | null>(null);

  const recorderRef = useRef<PcmRecorder | null>(null);
  const timerRef = useRef<number | null>(null);
  const generationRef = useRef(0);
  const startingRef = useRef(false);
  const playerRef = useRef(player);
  playerRef.current = player;

  const segment: TranscriptSegmentView | undefined = segments[index];
  const result = segment ? results[segment.segment_id] : undefined;
  const maxAttemptMs = segment ? Math.min(55_000, Math.max(6_000, 2 * (segment.end_ms - segment.start_ms) + 2_000)) : 0;

  const clearTimer = () => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
  };

  // The effect below revokes each replaced or unmounted object URL.
  const replaceRecordingUrl = useCallback((next: string | null) => setRecordingUrl(next), []);

  useEffect(() => () => {
    generationRef.current += 1;
    clearTimer();
    recorderRef.current?.dispose();
    playerRef.current.pause();
  }, []);

  useEffect(() => () => {
    if (recordingUrl) URL.revokeObjectURL(recordingUrl);
  }, [recordingUrl]);

  function listen() {
    if (!segment) return;
    setListening(true);
    player.playClip(segment.start_ms, segment.end_ms, () => setListening(false));
  }

  async function startRecording() {
    if (!segment || phase !== "idle" || startingRef.current || recorderRef.current) return;
    setError(null);
    player.pause();
    setListening(false);
    startingRef.current = true;
    const generation = generationRef.current;
    try {
      const recorder = await startPcmRecorder(setLevel);
      if (generation !== generationRef.current) {
        // Unmounted or moved on while the permission prompt was open.
        recorder.dispose();
        return;
      }
      recorderRef.current = recorder;
    } catch (cause) {
      setError(cause instanceof MicrophoneError && cause.kind === "denied"
        ? tr("Microphone access was blocked. Allow the microphone in your browser settings and try again.")
        : tr("No microphone is available in this browser."));
      return;
    } finally {
      startingRef.current = false;
    }
    const startedAt = performance.now();
    setElapsedMs(0);
    setPhase("recording");
    timerRef.current = window.setInterval(() => {
      const elapsed = performance.now() - startedAt;
      setElapsedMs(elapsed);
      if (elapsed >= maxAttemptMs) void stopRecording();
    }, 100);
  }

  async function stopRecording() {
    const recorder = recorderRef.current;
    if (!recorder || !segment) return;
    recorderRef.current = null;
    clearTimer();
    const samples = recorder.stop();
    if (pcmDurationMs(samples) < MIN_ATTEMPT_MS) {
      setPhase("idle");
      setError(tr("That was too short. Say the whole sentence, then press Stop."));
      return;
    }
    replaceRecordingUrl(URL.createObjectURL(encodeWav(samples)));
    setPhase("assessing");
    const generation = ++generationRef.current;
    const segmentId = segment.segment_id;
    try {
      const assessment = await speaking.assessShadowing(libraryItemId, segmentId, samples, regionId);
      if (generation !== generationRef.current) return;
      setResults((previous) => ({ ...previous, [segmentId]: assessment }));
    } catch (cause) {
      if (generation !== generationRef.current) return;
      setError(speakingErrorMessage(cause instanceof ApiError ? cause : null));
    } finally {
      if (generation === generationRef.current) setPhase("idle");
    }
  }

  function go(next: number) {
    if (phase !== "idle" || next < 0 || next >= segments.length) return;
    generationRef.current += 1;
    player.pause();
    setListening(false);
    setIndex(next);
    setError(null);
    replaceRecordingUrl(null);
  }

  if (!segment) {
    return <p className="muted"><T>This transcript has no sentences short enough to shadow.</T></p>;
  }

  return (
    <div className="stack shadowing-panel">
      <div className="row between">
        <span className="muted small"><T>Sentence</T> {index + 1} <T>of</T> {segments.length}</span>
        <div className="row">
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => go(index - 1)} disabled={index === 0 || phase !== "idle"}><T>Previous</T></button>
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => go(index + 1)} disabled={index >= segments.length - 1 || phase !== "idle"}><T>Next</T></button>
        </div>
      </div>

      <p className="shadowing-sentence" lang={languageCode}>{segment.text}</p>
      {segment.translation ? (
        <label className="toggle small">
          <input type="checkbox" checked={showTranslation} onChange={(event) => setShowTranslation(event.target.checked)} />
          <T>Show translation</T>
        </label>
      ) : null}
      {showTranslation && segment.translation ? (
        <p className="translation" lang={segment.translation.language_code}>{segment.translation.text}</p>
      ) : null}

      <div className="row">
        <button type="button" className="dl-btn dl-btn--secondary" onClick={listen} disabled={phase !== "idle"}>
          {listening ? <T>Playing…</T> : <T>Listen</T>}
        </button>
        {phase === "recording" ? (
          <button type="button" className="dl-btn record recording" onClick={() => void stopRecording()}>
            <T v1={(elapsedMs / 1000).toFixed(1)}>{"Stop · {v1}s"}</T>
          </button>
        ) : (
          <button type="button" className="dl-btn record" onClick={() => void startRecording()} disabled={phase !== "idle"}>
            {phase === "assessing" ? <T>Scoring…</T> : result ? <T>Record again</T> : <T>Record</T>}
          </button>
        )}
      </div>
      {phase === "recording" ? (
        <div className="mic-meter" role="meter" aria-label={t("Microphone level")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level * 100)}>
          <span style={{ width: `${Math.round(level * 100)}%` }} />
        </div>
      ) : null}
      {error ? <p className="banner error" role="alert">{error}</p> : null}
      {phase === "assessing" ? <p role="status" className="muted"><T>Checking your pronunciation…</T></p> : null}

      {result ? (
        <div className="stack shadowing-result" aria-live="polite">
          <div className="row">
            <ScoreRing value={result.scores.pronunciation} label="Pronunciation" />
            <div className="stack tight">
              <strong>{t(BAND_COPY[result.band].title)}</strong>
              <span className="muted small">{t(BAND_COPY[result.band].hint)}</span>
            </div>
          </div>
          <ScoreBars scores={result.scores} />
          <WordFeedback words={result.words} />
          {recordingUrl ? (
            <div className="stack tight">
              <span className="small muted"><T>Your recording</T></span>
              <audio controls src={recordingUrl} />
            </div>
          ) : null}
          <div className="row">
            <button type="button" className="dl-btn dl-btn--primary" onClick={() => go(index + 1)} disabled={index >= segments.length - 1}>
              <T>Next sentence</T>
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
