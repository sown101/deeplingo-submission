import { useState } from "react";
import { Icon } from "../../../design/notebookIcons";
import { T, useT } from "../../../i18n/i18n";
import type { WordImage } from "../notebookApi";
import type { NotebookWord, ShowOptions } from "./model";

// One colour per word, so a word without a picture always looks the same.
function swatch(text: string) {
  const hue = Array.from(text).reduce((sum, char) => sum + char.codePointAt(0)!, 0) % 360;
  return { background: `linear-gradient(135deg,hsl(${hue} 45% 52%),hsl(${(hue + 40) % 360} 50% 38%))`, color: "hsl(0 0% 100%)" };
}

export function WordPicture({ text, image, className = "nbp-word__img" }: { text: string; image: WordImage | null | undefined; className?: string }) {
  const [broken, setBroken] = useState<string | null>(null);
  const url = image ? image.thumbnailUrl ?? image.imageUrl : null;
  if (url && broken !== url) {
    return <img className={className} src={url} alt={image?.title ?? text} loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(url)} />;
  }
  return <span className={className} style={swatch(text)} aria-hidden="true">{Array.from(text)[0]?.toUpperCase()}</span>;
}

// The whole tile is one button drawn behind the text; the note and speaker buttons sit beside it, not inside it.
export function WordTile({ word, show, picture, withPicture, selected, selecting, playing, onOpen, onToggle, onNote, onPlay }: {
  word: NotebookWord;
  show: ShowOptions;
  picture: WordImage | null | undefined;
  withPicture: boolean;
  selected: boolean;
  selecting: boolean;
  playing: boolean;
  onOpen: () => void;
  onToggle: () => void;
  onNote: () => void;
  onPlay: () => void;
}) {
  const t = useT();
  const hit = selecting
    ? { "aria-pressed": selected, "aria-label": t("Select {word}", { word: word.text }), onClick: onToggle }
    : { "aria-label": t("Open {word}", { word: word.text }), onClick: onOpen };
  return <li className={selected ? "nbp-word is-selected" : "nbp-word"} data-concept-id={word.conceptId}>
    <button type="button" className="nbp-word__hit" {...hit} />
    {selecting ? <span className="nbp-word__pick" aria-hidden="true"><Icon name="check" /></span> : null}
    {withPicture ? <WordPicture text={word.text} image={picture} /> : null}
    <div className="nbp-word__body">
      <div className={show.word ? "nbp-word__term" : "nbp-word__term is-hidden"} lang={word.languageCode}>
        {word.text}{word.traditional ? <small>【{word.traditional}】</small> : null}
      </div>
      <div className="nbp-word__line">
        {word.reading ? <span className={show.reading ? "nbp-word__reading" : "nbp-word__reading is-hidden"}>{word.reading}</span> : null}
        {word.status === "suspended" ? <span className="nbp-word__status"><T>Paused</T></span> : null}
      </div>
      {word.gloss ? <div className={show.meaning ? "nbp-word__mean" : "nbp-word__mean is-hidden"}>{word.gloss}</div> : null}
      {show.notes && word.note ? <div className="nbp-word__note">{word.note}</div> : null}
      <button type="button" className={word.note ? "nbp-word__chip has" : "nbp-word__chip"} aria-label={t("Note for {word}", { word: word.text })} onClick={onNote}>
        <Icon name="note" /><T>Note</T>
      </button>
    </div>
    <button type="button" className={playing ? "nb-spk play" : "nb-spk"} aria-label={t("Listen to {word}", { word: word.text })} title={t("Listen")} onClick={onPlay}>
      <Icon name="sound" />
    </button>
  </li>;
}
