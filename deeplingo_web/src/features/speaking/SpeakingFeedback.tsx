import { useState } from "react";
import type { ApiError } from "../../lib/api/errors";
import type { FeedbackBand, SpeakingScores, SpeakingWord } from "./speakingModels";
import { T, useT, tr } from "../../i18n/i18n";

export const BAND_COPY: Record<FeedbackBand, { title: string; hint: string }> = {
  excellent: { title: "Excellent!", hint: "Clear and steady. Try a longer sentence next." },
  good: { title: "Good job", hint: "Clear overall — polish the highlighted words." },
  fair: { title: "Getting there", hint: "Listen again and copy the rhythm." },
  retry: { title: "Let's try again", hint: "Play the original, then repeat slowly and clearly." },
};

export const ERROR_LABELS: Record<SpeakingWord["error_type"], string> = {
  none: "Good",
  mispronunciation: "Mispronounced",
  omission: "Missed",
  insertion: "Extra word",
  unexpected_break: "Unexpected pause",
  missing_break: "Missing pause",
  monotone: "Flat intonation",
  other: "Check this word",
};

export function speakingErrorMessage(error: ApiError | null): string {
  const code = error?.detail.code;
  switch (code) {
    case "voice_consent_required":
      return tr("Allow voice processing in Profile to practise speaking.");
    case "no_speech_detected":
      return tr("We could not hear any speech. Check your microphone and speak a little louder.");
    case "audio_too_long":
      return tr("That recording was too long. Repeat just this sentence.");
    case "speaking_language_unsupported":
      return tr("Speaking practice is not available for this language yet.");
    case "speaking_rate_limited":
      return tr("You're practising fast! Wait a few seconds and try again.");
    case "speech_service_busy":
      return tr("The speech service is busy. Try again in a moment.");
    default:
      if (error?.kind === "network" || error?.kind === "timeout") return tr("Connection problem. Check your network and retry.");
      return tr("Speaking practice is temporarily unavailable. Please try again.");
  }
}

export function ScoreRing({ value, label }: { value: number; label: string }) {
  const t = useT();
  const rounded = Math.round(value);
  const tone = rounded >= 80 ? "good" : rounded >= 60 ? "fair" : "low";
  return (
    <div className={`score-ring ${tone}`} role="img" aria-label={t("{label} {n} out of 100", { label: t(label), n: rounded })}
      style={{ ["--score" as string]: `${rounded}` }}>
      <span>{rounded}</span>
    </div>
  );
}

export function ScoreBars({ scores }: { scores: SpeakingScores }) {
  const t = useT();
  const rows: [string, number | null][] = [
    ["Accuracy", scores.accuracy],
    ["Fluency", scores.fluency],
    ["Completeness", scores.completeness],
    ["Intonation", scores.prosody],
  ];
  return (
    <ul className="score-bars">
      {rows.filter(([, value]) => value !== null).map(([name, value]) => (
        <li key={name}>
          <span>{t(name)}</span>
          <span className="skill-bar" aria-hidden="true"><span className="skill-bar-fill" style={{ width: `${Math.round(value!)}%` }} /></span>
          <span className="small">{Math.round(value!)}</span>
        </li>
      ))}
    </ul>
  );
}

export function WordFeedback({ words }: { words: SpeakingWord[] }) {
  const t = useT();
  const [selected, setSelected] = useState<number | null>(null);
  if (words.length === 0) return null;
  const detail = selected !== null ? words[selected] : null;
  return (
    <div className="stack tight">
      <div className="word-feedback" aria-label={t("Word by word feedback")}>
        {words.map((word, index) => {
          const tone = word.error_type === "omission" ? "missed"
            : word.error_type === "insertion" ? "extra"
              : word.accuracy >= 80 && word.error_type === "none" ? "good"
                : word.accuracy >= 60 ? "fair" : "low";
          return (
            <button key={`${word.word}-${index}`} type="button" className={`word-chip ${tone}`}
              aria-pressed={selected === index}
              onClick={() => setSelected(selected === index ? null : index)}>
              {word.word}
            </button>
          );
        })}
      </div>
      {detail ? (
        <p className="small word-detail" role="status">
          <strong>{detail.word}</strong> · {t(ERROR_LABELS[detail.error_type])} · {Math.round(detail.accuracy)}/100
          {detail.phonemes.length > 0 ? (
            <span className="phonemes">
              {" "}/
              {detail.phonemes.map((item, index) => (
                <span key={index} className={item.accuracy < 60 ? "weak" : undefined}>{item.phoneme}</span>
              ))}
              /
            </span>
          ) : null}
        </p>
      ) : <p className="small muted"><T>Tap a word to see details. Red words need the most work.</T></p>}
    </div>
  );
}
