import { useQuery } from "@tanstack/react-query";
import { Navigate, useSearchParams } from "react-router-dom";
import { useContainer } from "../../app/container";
import { T, useT } from "../../i18n/i18n";
import { levelOfRung, type NotebookWord } from "./notebook/model";
import { NotebookPage } from "./NotebookPage";
import { RUNG_LABELS, type MyWord } from "./wordsModels";

function toNotebookWord(word: MyWord): NotebookWord {
  return {
    conceptId: word.conceptId, languageCode: word.languageCode, text: word.text, traditional: word.traditional, reading: word.reading,
    gloss: word.gloss, note: word.note, favorite: word.favorite, status: word.status === "backlog" ? "active" : word.status, rung: word.rung,
    levelLabel: word.levelLabel, aboveLevel: word.aboveLevel, saved: word.saved, nextReviewAt: word.nextReviewAt,
  };
}

// One level of the shelf chart (?level=0..4) in the language being learned. The "All words" page was removed (owner
// decision 2026-11-14): without a level this goes back to the shelf.
export function MyWordsScreen() {
  const t = useT();
  const { words, onboarding } = useContainer();
  const [params] = useSearchParams();
  const rawLevel = params.get("level");
  const level = rawLevel !== null && /^[0-4]$/.test(rawLevel) ? Number(rawLevel) : null;
  const profileQuery = useQuery({ queryKey: ["language-profile"], queryFn: () => onboarding.loadProfile() });
  const language = profileQuery.data?.learning_language ?? null;
  const wordsQuery = useQuery({
    queryKey: ["my-words", language],
    queryFn: () => words.list(language ?? undefined),
    enabled: profileQuery.isSuccess && level !== null,
  });

  if (level === null) return <Navigate to="/words/lists" replace />;
  if (wordsQuery.isLoading || profileQuery.isLoading) return <p role="status"><T>Loading your words…</T></p>;
  if (wordsQuery.isError || profileQuery.isError || !wordsQuery.data) {
    return <div role="alert">
      <p className="error"><T>Your words could not be loaded.</T></p>
      <button type="button" className="dl-btn dl-btn--secondary" onClick={() => void (profileQuery.isError ? profileQuery.refetch() : wordsQuery.refetch())}><T>Retry</T></button>
    </div>;
  }

  const shown = wordsQuery.data.words.map(toNotebookWord).filter(word => levelOfRung(word.rung) === level);
  return <NotebookPage scope={`level-${level}`} listId={null} title={t("Level: {name}", { name: t(RUNG_LABELS[level]) })}
    languageCode={language ?? ""} words={shown} />;
}
