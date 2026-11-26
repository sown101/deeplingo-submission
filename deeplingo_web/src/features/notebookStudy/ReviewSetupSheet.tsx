import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../../design/notebookIcons";
import { T, useT } from "../../i18n/i18n";
import { StudyDialog, StudySwitch } from "./StudyParts";
import { MAX_REVIEW_WORDS, isHanWord, reviewHref, scopeHref, type ReviewType, type StudyDisplay } from "./studySession";
import type { NotebookScope, StudyWord } from "./studyTypes";

const SCHEDULE_TYPES: { key: ReviewType; title: string }[] = [
  { key: "choice", title: "Multiple choice" },
  { key: "match", title: "Match pairs" },
  { key: "order", title: "Order the sentence" },
];
const SPEAK_TYPE: { key: ReviewType; title: string } = { key: "speak", title: "Pronunciation" };
const WRITE_TYPE: { key: ReviewType; title: string } = { key: "write", title: "Write the word" };
const DEFAULT_PICKED = 5;

// The notebook's Review: the words, how questions show, and which question types to mix. The server
// builds and grades every question.
export function ReviewSetupSheet({ scope, words, preselected, onClose }: { scope: NotebookScope; words: StudyWord[]; preselected?: string[]; onClose: () => void }) {
  const t = useT();
  const navigate = useNavigate();
  const [picked, setPicked] = useState(() => new Set(preselected ?? words.slice(0, DEFAULT_PICKED).map((word) => word.conceptId)));
  const [display, setDisplay] = useState<StudyDisplay>({ showAnswer: true, images: true, reading: true });
  const [types, setTypes] = useState<Set<ReviewType>>(new Set<ReviewType>(["choice"]));

  const toggleWord = (id: string) => setPicked((current) => {
    const next = new Set(current);
    if (!next.delete(id)) next.add(id);
    return next;
  });
  const toggleType = (key: ReviewType) => setTypes((current) => {
    const next = new Set(current);
    if (!next.delete(key)) next.add(key);
    return next;
  });
  const typeSwitch = ({ key, title }: { key: ReviewType; title: string }) => (
    <StudySwitch key={key} label={t(title)} on={types.has(key)} onToggle={() => toggleType(key)} />
  );

  const chosen = words.filter((word) => picked.has(word.conceptId));
  const language = chosen[0]?.languageCode ?? words[0]?.languageCode ?? "";
  // Writing is for Chinese and Japanese characters only: the switch shows when the notebook has such words.
  const practiceTypes = words.some(isHanWord) ? [SPEAK_TYPE, WRITE_TYPE] : [SPEAK_TYPE];
  const ordered = [...SCHEDULE_TYPES, ...practiceTypes].map((type) => type.key).filter((key) => types.has(key));

  return (
    <StudyDialog label={t("Review settings")} className="sheet" onClose={onClose}>
      <div className="nb-grip" />
      <div className="nb-m-head">
        <span><T>Review settings</T></span>
        <button type="button" aria-label={t("Close")} onClick={onClose}><Icon name="close" /></button>
      </div>
      <div className="nb-row-between">
        <span><T n={chosen.length}>{"Words: {n}"}</T></span>
        <button type="button" className="nb-link" onClick={() => setPicked(new Set(words.map((word) => word.conceptId)))}><T>Select all</T></button>
      </div>
      <div className="nb-chips">
        {words.map((word) => (
          <button key={word.conceptId} type="button" className={`nb-chip${picked.has(word.conceptId) ? " on" : ""}`} aria-pressed={picked.has(word.conceptId)}
            lang={word.languageCode} onClick={() => toggleWord(word.conceptId)}>
            {word.text}{word.traditional ? `【${word.traditional}】` : ""}
          </button>
        ))}
      </div>
      <StudySwitch label={t("Show the answer right away")} on={display.showAnswer} onToggle={() => setDisplay({ ...display, showAnswer: !display.showAnswer })} />
      <StudySwitch label={t("Images")} on={display.images} onToggle={() => setDisplay({ ...display, images: !display.images })} />
      <StudySwitch label={t("Show reading")} on={display.reading} onToggle={() => setDisplay({ ...display, reading: !display.reading })} />
      <div className="nb-sep" />
      <h3 className="st-group"><T>Counts toward your schedule</T></h3>
      {SCHEDULE_TYPES.map(typeSwitch)}
      <h3 className="st-group"><T>Practice only</T></h3>
      {practiceTypes.map(typeSwitch)}
      {chosen.length > MAX_REVIEW_WORDS ? <p className="st-note"><T n={MAX_REVIEW_WORDS}>{"A review takes the first {n} chosen words."}</T></p> : null}
      <button type="button" className="nb-btn main wide" disabled={chosen.length === 0 || types.size === 0 || !language}
        onClick={() => navigate(reviewHref(language, chosen.map((word) => word.conceptId), ordered, display, scopeHref(scope)))}><T>Start</T></button>
    </StudyDialog>
  );
}
