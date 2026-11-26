import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { Icon } from "../../../design/notebookIcons";
import { T, useT } from "../../../i18n/i18n";
import type { WordCharacter, WordCompound, WordImage, WordSense } from "../notebookApi";
import { RUNG_LABELS, type WordStatus } from "../wordsModels";
import { webUrl, type NotebookWord } from "./model";
import { NotebookDialog } from "./NotebookDialog";
import { FirstExample, WordExamples } from "./WordExamples";
import { WordPicture } from "./WordTile";
import { LatestPronunciationNote } from "../../notebookStudy/PronunciationResult";

type Tab = "vocabulary" | "characters" | "examples" | "compounds";

const STATUS_LABEL: Record<WordStatus, string> = { active: "Learning", backlog: "Learning", suspended: "Paused" };

// One word in full. Read-only reference data comes from the server; every section without data is left out.
export function WordSheet({ word, inNotebook, image, playing, audioFailed, onPlay, onImage, onChanged, onPronounce, onNote, onRemove, onClose }: {
  word: NotebookWord;
  inNotebook: boolean;
  image: WordImage | null | undefined;
  playing: boolean;
  audioFailed: boolean;
  onPlay: () => void;
  onImage: (image: WordImage | null) => void;
  onChanged: () => void;
  onPronounce: () => void;
  onNote: () => void;
  onRemove: () => void;
  onClose: () => void;
}) {
  const t = useT();
  const { notebook, words } = useContainer();
  const queryClient = useQueryClient();
  const id = word.conceptId;
  const zh = word.languageCode.startsWith("zh");
  const [tab, setTab] = useState<Tab>("vocabulary");
  const [section, setSection] = useState("vocabulary");
  const main = useRef<HTMLDivElement | null>(null);
  const details = useQuery({ queryKey: ["word-details", id], queryFn: () => notebook.details(id) });
  const imageKey = ["word-image", id];
  const picture = useQuery({
    queryKey: imageKey,
    queryFn: async () => (await notebook.images([id]))[0] ?? null,
    initialData: image,
    staleTime: Infinity,
  });
  const another = useMutation({
    mutationFn: async () => (await notebook.images([id], id))[0] ?? null,
    onSuccess: (found) => { queryClient.setQueryData(imageKey, found); onImage(found); },
  });
  const status = useMutation({
    mutationFn: (next: WordStatus) => words.setStatus(id, next),
    onSuccess: onChanged,
  });
  const favorite = useMutation({
    mutationFn: () => notebook.setPersonal(id, { favorite: !word.favorite }),
    onSuccess: onChanged,
  });

  const data = details.data;
  const level = data?.level ?? word.levelLabel;
  const reading = word.reading ?? data?.reading ?? null;
  const traditional = word.traditional ?? data?.traditional ?? null;
  const groups = groupSenses(data?.senses ?? []);
  const shownPicture = picture.data;
  const tabs: { key: Tab; label: string }[] = [
    { key: "vocabulary", label: t("Vocabulary") },
    ...(zh ? [{ key: "characters" as const, label: t("Characters") }] : []),
    ...(word.saved ? [{ key: "examples" as const, label: t("Examples") }] : []),
    ...(zh ? [{ key: "compounds" as const, label: t("Compounds") }] : []),
  ];
  const sections = [
    { key: "vocabulary", label: t("Vocabulary") },
    ...groups.filter(group => group.pos).map(group => ({ key: group.key, label: group.pos as string })),
    ...(shownPicture ? [{ key: "picture", label: t("Picture") }] : []),
  ];
  const goTo = (key: string) => {
    setSection(key);
    main.current?.querySelector(`[data-section="${key}"]`)?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  };

  const head = <div className="nb-row-between">
    <div className="nbp-tabs" role="tablist" aria-label={word.text}>
      {tabs.map(item => <button key={item.key} type="button" role="tab" aria-selected={tab === item.key} className={tab === item.key ? "on" : undefined} onClick={() => setTab(item.key)}>{item.label}</button>)}
    </div>
    <button type="button" className="nbp-x" aria-label={t("Close")} title={t("Close")} onClick={onClose}><Icon name="close" /></button>
  </div>;

  return <NotebookDialog label={word.text} head={head} className="nbp-sheet" onClose={onClose}>
    <div className={tab === "vocabulary" && sections.length > 1 ? "nbp-sheet__body" : "nbp-sheet__body one"}>
      {tab === "vocabulary" && sections.length > 1 ? <nav className="nbp-sheet__nav" aria-label={t("Sections")}>
        {sections.map(item => <button key={item.key} type="button" className={section === item.key ? "on" : undefined} onClick={() => goTo(item.key)}>{item.label}</button>)}
      </nav> : null}
      <div className="nbp-sheet__main" ref={main} role="tabpanel">
        {tab === "vocabulary" ? <>
          <section className="nbp-block" data-section="vocabulary">
            <div className="nb-row-between">
              <div className="nbp-sheet__word" lang={word.languageCode}>{word.text}{traditional ? <small>【{traditional}】</small> : null}</div>
              <div className="nbp-sheet__mini">
                <button type="button" className={playing ? "on" : undefined} aria-label={t("Listen to {word}", { word: word.text })} title={t("Listen")} onClick={onPlay}><Icon name="sound" /></button>
                <button type="button" className={word.favorite ? "on heart" : "heart"} aria-pressed={word.favorite} aria-label={t("Favourite")} title={t("Favourite")} disabled={favorite.isPending} onClick={() => favorite.mutate()}><Icon name="heart" /></button>
              </div>
            </div>
            {reading ? <div className="nbp-sheet__reading">{reading}</div> : null}
            {audioFailed ? <p className="small muted" role="status"><T>This word could not be played.</T></p> : null}
            <div className="nbp-pills">
              <button type="button" className="nbp-tag" onClick={onPronounce}><Icon name="mic" /><T>Pronunciation</T></button>
              <button type="button" className={word.note ? "nbp-tag has" : "nbp-tag"} onClick={onNote}><Icon name="note" /><T>Note</T></button>
            </div>
            <div className="nbp-pills">
              {level ? <span className="nbp-tag lv">{level}</span> : null}
              <span className="nbp-tag">{t(STATUS_LABEL[word.status])}</span>
              <span className="nbp-tag" title={t("How far you have got with this word")}>{t(RUNG_LABELS[word.rung] ?? RUNG_LABELS[0])}</span>
              {word.aboveLevel ? <span className="nbp-tag"><T>Above your level</T></span> : null}
              {word.nextReviewAt ? <span className="nbp-tag"><T date={new Date(word.nextReviewAt).toLocaleDateString()}>{"Next review {date}"}</T></span> : null}
            </div>
            {word.saved ? <LatestPronunciation conceptId={id} /> : null}
          </section>
          <section className="nbp-block">
            <strong><T>Meaning</T></strong>
            {word.gloss ? <div>{word.gloss}</div> : null}
            {groups.filter(group => !group.pos).map(group => <SenseList key={group.key} senses={group.senses} />)}
            {word.note ? <p className="nbp-sheet__note">{word.note}</p> : null}
            {word.saved ? <FirstExample conceptId={id} /> : null}
            {details.isLoading ? <p className="small muted" role="status"><T>Loading…</T></p> : null}
            {details.isError ? <p className="error small" role="alert"><T>The dictionary details could not be loaded.</T></p> : null}
          </section>
          {groups.filter(group => group.pos).map(group => <section key={group.key} className="nbp-block" data-section={group.key}>
            <strong>{group.pos}</strong>
            <SenseList senses={group.senses} />
          </section>)}
          {shownPicture ? <section className="nbp-block" data-section="picture">
            <strong><T>Picture</T></strong>
            <WordPicture text={word.text} image={shownPicture} className="nbp-sheet__img" />
            <PictureCredit image={shownPicture} />
          </section> : null}
          <button type="button" className="nb-chip-btn nbp-another" disabled={another.isPending} onClick={() => another.mutate()}>
            <Icon name="refresh" />{another.isPending ? <T>Looking…</T> : <T>Another picture</T>}
          </button>
          {another.isError ? <p className="error small" role="alert"><T>Another picture could not be found. Please try again later.</T></p> : null}
        </> : null}
        {tab === "characters" ? <ReferenceList items={data?.characters.map(asRow)} loading={details.isLoading} empty={t("No character details for this word yet.")} /> : null}
        {tab === "examples" ? <section className="nbp-block"><WordExamples conceptId={id} /></section> : null}
        {tab === "compounds" ? <ReferenceList items={data?.compounds.map(asRow)} loading={details.isLoading} empty={t("No compounds for this word yet.")} /> : null}
      </div>
    </div>
    {status.isError ? <p className="error small" role="alert"><T>That word could not be updated. Please try again.</T></p> : null}
    <div className="nb-m-foot">
      <button type="button" className="nb-btn" disabled={status.isPending} onClick={() => status.mutate(word.status === "suspended" ? "active" : "suspended")}>
        <Icon name={word.status === "suspended" ? "play" : "pause"} />
        {word.status === "suspended" ? <T>Resume review</T> : <T>Pause review</T>}
      </button>
      <button type="button" className="nb-btn red" onClick={onRemove}>{inNotebook ? <T>Remove from notebook</T> : <T>Remove word</T>}</button>
    </div>
  </NotebookDialog>;
}

interface SenseGroup { key: string; pos: string | null; senses: WordSense[] }

function groupSenses(senses: WordSense[]): SenseGroup[] {
  const groups = new Map<string, SenseGroup>();
  for (const sense of senses) {
    const key = `pos-${sense.partOfSpeech ?? "none"}`.replace(/[^\w-]/g, "_");
    const group = groups.get(key) ?? { key, pos: sense.partOfSpeech, senses: [] };
    group.senses.push(sense);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function SenseList({ senses }: { senses: WordSense[] }) {
  return <ul className="nbp-sense-list">
    {senses.map((sense, index) => <li key={index}>{sense.reading ? <span className="muted">[{sense.reading}] </span> : null}{sense.text}</li>)}
  </ul>;
}

function PictureCredit({ image }: { image: WordImage }) {
  const source = webUrl(image.sourceUrl);
  const credit = [image.creator, image.license?.toUpperCase()].filter(Boolean).join(", ");
  if (!credit && !source) return null;
  return <small className="dictionary-credit muted">
    <T>Picture:</T> {source ? <a href={source} target="_blank" rel="noopener noreferrer">{credit || image.title || source}</a> : credit}
  </small>;
}

interface ReferenceRow { key: string; text: string; reading: string | null; meaning: string | null }

function asRow(item: WordCharacter | WordCompound): ReferenceRow {
  const text = "character" in item ? item.character : item.text;
  return { key: text, text, reading: item.reading, meaning: item.meaning };
}

function ReferenceList({ items, loading, empty }: { items: ReferenceRow[] | undefined; loading: boolean; empty: string }) {
  if (loading) return <p className="small muted" role="status"><T>Loading…</T></p>;
  if (!items?.length) return <p className="small muted">{empty}</p>;
  return <ul className="nbp-reference">
    {items.map(item => <li key={item.key} className="nbp-block">
      <span className="nbp-reference__text" lang="zh">{item.text}</span>
      {item.reading ? <span className="nbp-sheet__reading">{item.reading}</span> : null}
      {item.meaning ? <span>{item.meaning}</span> : null}
    </li>)}
  </ul>;
}

// The learner's latest pronunciation result for this word, kept on the server after each attempt.
function LatestPronunciation({ conceptId }: { conceptId: string }) {
  const { review } = useContainer();
  const latest = useQuery({ queryKey: ["word-pronunciation", conceptId], queryFn: () => review.latestPronunciation(conceptId), retry: false });
  return latest.data ? <LatestPronunciationNote latest={latest.data} /> : null;
}
