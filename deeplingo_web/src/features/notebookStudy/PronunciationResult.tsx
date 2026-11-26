import { T, useT } from "../../i18n/i18n";
import { BAND_COPY, ERROR_LABELS, ScoreBars, ScoreRing } from "../speaking/SpeakingFeedback";
import type { LatestPronunciation, PronunciationAssessment } from "../review/reviewModels";

const tone = (accuracy: number) => (accuracy >= 80 ? "good" : accuracy >= 60 ? "fair" : "low");

/**
 * Azure's whole result for a word: the overall score and band, accuracy, fluency, completeness and intonation (where
 * Azure scores it), then each spoken unit (a Chinese character is one syllable) with its error type and the accuracy of
 * every phoneme. Weak sounds are marked.
 */
export function PronunciationResult({ assessment, caption }: { assessment: PronunciationAssessment; caption?: string }) {
  const t = useT();
  const band = BAND_COPY[assessment.band];
  return (
    <section className="st-pr" aria-label={t("Pronunciation result")}>
      <div className="st-pr-head">
        <ScoreRing value={assessment.scores.pronunciation} label="Pronunciation" />
        <div>
          {caption ? <small className="st-note">{caption}</small> : null}
          <strong>{t(band.title)}</strong>
          <p className="st-note">{t(band.hint)}</p>
        </div>
      </div>
      <ScoreBars scores={assessment.scores} />
      {assessment.words.length ? <ul className="st-pr-words">
        {assessment.words.map((word, index) => (
          <li key={`${word.word}-${index}`} data-tone={word.error_type === "none" ? tone(word.accuracy) : "low"}>
            <span className="st-pr-word">{word.word}</span>
            <span className="st-pr-meta">{t(ERROR_LABELS[word.error_type])} · {Math.round(word.accuracy)}/100</span>
            {word.phonemes.length ? <span className="st-pr-phonemes" aria-label={t("Sounds")}>
              {word.phonemes.map((item, position) => (
                <span key={position} data-tone={tone(item.accuracy)} title={`${Math.round(item.accuracy)}/100`}>
                  {item.phoneme}<small>{Math.round(item.accuracy)}</small>
                </span>
              ))}
            </span> : null}
          </li>
        ))}
      </ul> : <p className="st-note"><T>No detail for each sound this time.</T></p>}
    </section>
  );
}

/** The word's latest stored result: the whole assessment when it was kept, else its score. */
export function LatestPronunciationNote({ latest }: { latest: LatestPronunciation }) {
  const t = useT();
  const when = latest.at ? new Date(latest.at).toLocaleDateString() : null;
  const caption = when ? t("Your latest result, {date}", { date: when }) : t("Your latest result");
  if (latest.assessment) return <PronunciationResult assessment={latest.assessment} caption={caption} />;
  return <p className="st-note">{caption}: <T n={Math.round(latest.score)}>{"Pronunciation score: {n}"}</T></p>;
}
