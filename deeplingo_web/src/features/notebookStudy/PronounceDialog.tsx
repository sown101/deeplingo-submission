import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { Icon } from "../../design/notebookIcons";
import { Mascot } from "../../design/Mascot";
import { T, useT } from "../../i18n/i18n";
import { useWordAudio } from "../words/useWordAudio";
import { AttemptControls } from "./AttemptControls";
import { LatestPronunciationNote } from "./PronunciationResult";
import { StudyDialog } from "./StudyParts";
import type { StudyWord } from "./studyTypes";
import { usePronunciationAttempt } from "./usePronunciationAttempt";

const SLOW_RATE = 0.7;

export function PronounceDialog({ words, initialIndex = 0, onClose }: { words: StudyWord[]; initialIndex?: number; onClose: () => void }) {
  const t = useT();
  const [index, setIndex] = useState(Math.min(Math.max(initialIndex, 0), Math.max(words.length - 1, 0)));
  const attempt = usePronunciationAttempt();
  const audio = useWordAudio();
  const word = words[index];
  const { review } = useContainer();
  const queryClient = useQueryClient();
  // The word's latest result is kept on the server; a new attempt becomes the latest.
  const latest = useQuery({
    queryKey: ["word-pronunciation", word?.conceptId], enabled: !!word, retry: false,
    queryFn: () => review.latestPronunciation(word!.conceptId),
  });
  useEffect(() => {
    if (attempt.result && word) void queryClient.invalidateQueries({ queryKey: ["word-pronunciation", word.conceptId] });
  }, [attempt.result, word, queryClient]);

  const close = () => { attempt.reset(); onClose(); };
  function go(next: number) {
    if (next === index) return;
    attempt.reset();
    setIndex(next);
  }
  const step = (delta: number) => go((index + delta + words.length) % words.length);

  return (
    <StudyDialog label={t("Pronunciation practice")} className="narrow" onClose={close}>
      <div className="nb-m-head">
        <span><T>Pronunciation practice</T> {word ? <small className="st-count">{index + 1}/{words.length}</small> : null}</span>
        <button type="button" aria-label={t("Close")} onClick={close}><Icon name="close" /></button>
      </div>
      {word ? <>
        <div className="st-speak-top">
          <Mascot state="listen" className="st-speak-mascot" />
          <p className="st-speak-quote"><T>Speak a little slowly, one clear sound at a time.</T></p>
        </div>
        <div className="st-speak-card">
          <div className="st-speak-word" lang={word.languageCode}>{word.text}{word.traditional ? `【${word.traditional}】` : ""}</div>
          <div className="st-mini">
            <button type="button" aria-label={t("Listen")} onClick={() => void audio.play(word.languageCode, word.text, 1, word.conceptId)}><Icon name="sound" /></button>
            <button type="button" aria-label={t("Listen slowly")} onClick={() => void audio.play(word.languageCode, word.text, SLOW_RATE, word.conceptId)}><Icon name="turtle" /></button>
          </div>
          {word.reading ? <div className="st-reading">{word.reading}</div> : null}
          {word.gloss ? <div>{word.gloss}</div> : null}
        </div>
        {audio.failed ? <p className="st-note" role="status"><T>Audio is not available for this word.</T></p> : null}
        <AttemptControls attempt={attempt} word={word} />
        {!attempt.result && latest.data ? <LatestPronunciationNote latest={latest.data} /> : null}
        <div className="st-rail">
          <button type="button" aria-label={t("Previous word")} onClick={() => step(-1)}><Icon name="back" /></button>
          <div className="nb-chips">
            {words.map((item, i) => (
              <button key={item.conceptId} type="button" className={`nb-chip${i === index ? " on" : ""}`} aria-current={i === index ? "true" : undefined}
                lang={item.languageCode} onClick={() => go(i)}>{item.text}</button>
            ))}
          </div>
          <button type="button" aria-label={t("Next word")} onClick={() => step(1)}><Icon name="chevron" /></button>
        </div>
      </> : <p><T>This notebook has no words yet.</T></p>}
    </StudyDialog>
  );
}
