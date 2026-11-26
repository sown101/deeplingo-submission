import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { T } from "../../i18n/i18n";
import type { ListDetail } from "./listsModels";
import type { NotebookWord } from "./notebook/model";
import { NotebookPage } from "./NotebookPage";

// L1b: one list. The server resolves every word; nothing here makes a word known.
export function WordListScreen() {
  const { listId = "" } = useParams();
  const { lists } = useContainer();
  const detail = useQuery({ queryKey: ["word-list", listId], queryFn: () => lists.detail(listId) });

  if (detail.isLoading) return <p role="status"><T>Loading the notebook…</T></p>;
  if (detail.isError || !detail.data) {
    const missing = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <section className="stack" role="alert">
        <p className="error">{missing ? <T>This notebook was not found.</T> : <T>The notebook could not be loaded.</T>}</p>
        <Link className="dl-btn dl-btn--secondary" to="/words/lists"><T>Back to notebooks</T></Link>
      </section>
    );
  }
  const list = detail.data;
  return <NotebookPage key={list.id} scope={list.id} listId={list.id} title={list.name} languageCode={list.languageCode} words={notebookWords(list)} waiting={list.waiting} />;
}

function notebookWords(list: ListDetail): NotebookWord[] {
  return list.words.map(word => ({
    conceptId: word.conceptId, languageCode: list.languageCode, text: word.text, traditional: word.traditional, reading: word.reading,
    gloss: word.gloss, note: word.note, favorite: word.favorite, status: word.status === "backlog" ? "active" : word.status, rung: word.rung,
    levelLabel: word.levelLabel, aboveLevel: word.aboveLevel, saved: true, nextReviewAt: null,
  }));
}
