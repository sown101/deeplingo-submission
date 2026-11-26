import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { Icon } from "../../../design/notebookIcons";
import { T, useT, tr } from "../../../i18n/i18n";
import { ApiError } from "../../../lib/api/errors";
import { listErrorCode } from "../listsModels";
import { aboveLevelNotice, type AboveLevelNotice, type DictionaryEntryResult, type MyWord } from "../wordsModels";
import { NotebookDialog } from "./NotebookDialog";

interface Pick {
  entryId: string;
  senseId: string;
  headword: string;
  acknowledged?: boolean;
}

// Words come from the dictionary: look one up, then choose the meaning to learn.
export function AddWordDialog({ languageCode, listId, onChanged, onClose }: {
  languageCode: string;
  listId: string | null;
  onChanged: () => void;
  onClose: () => void;
}) {
  const t = useT();
  const { words, lists } = useContainer();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DictionaryEntryResult[] | null>(null);
  const [added, setAdded] = useState<MyWord | null>(null);
  // A word above the learner's declared level is added only after one confirmation.
  const [pending, setPending] = useState<{ pick: Pick; notice: AboveLevelNotice } | null>(null);
  const search = useMutation({
    mutationFn: (text: string) => words.search(languageCode, text),
    onSuccess: (found) => setResults(found),
  });
  const save = useMutation({
    mutationFn: async (pick: Pick) => {
      const word = await words.save({
        source: "dictionary", language_code: languageCode, entry_id: pick.entryId, sense_id: pick.senseId,
        ...(pick.acknowledged ? { acknowledge_above_level: true } : {}),
      });
      if (listId) await lists.addWord(listId, word.conceptId);
      return word;
    },
    onSuccess: (word) => {
      setAdded(word);
      setPending(null);
      onChanged();
    },
    onError: (error, pick) => {
      const notice = aboveLevelNotice(error);
      if (notice) setPending({ pick, notice });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = query.trim();
    if (!text) return;
    setAdded(null);
    setPending(null);
    search.mutate(text);
  }

  return <NotebookDialog title={t("Add word")} size="narrow" onClose={onClose}>
    <form className="nb-lookup" onSubmit={submit} role="search">
      <button type="submit" className="nbp-lookup-go" aria-label={t("Search")} title={t("Search")} disabled={!query.trim() || search.isPending}><Icon name="search" /></button>
      <label htmlFor="add-word-query" className="sr-only"><T>Add a word</T></label>
      <input id="add-word-query" type="search" autoFocus placeholder={t("Add a word, e.g. “take off”")} value={query} maxLength={80}
             onChange={(event) => setQuery(event.target.value)} />
    </form>
    {search.isError ? <p className="error" role="alert">{searchError(search.error)}</p> : null}
    {added ? <p role="status" className="feedback correct">
      <T added={added.text}>{listId ? "“{added}” was added to this notebook." : "“{added}” was added to your words."}</T>
    </p> : null}
    {pending ? <div role="alert" className="above-level-confirm stack">
      <p>
        {pending.notice.level
          ? <T word={pending.pick.headword} level={pending.notice.level}>{"“{word}” is {level} level"}</T>
          : <T word={pending.pick.headword}>{"“{word}” is above level"}</T>}
        {pending.notice.declaredLevel ? <T declared={pending.notice.declaredLevel}>{", higher than the {declared} you set"}</T> : ""}<T>. It may be hard for now. Add it anyway?</T>
      </p>
      <p className="nbp-row">
        <button type="button" className="nb-btn main" disabled={save.isPending} onClick={() => save.mutate({ ...pending.pick, acknowledged: true })}><T>Add anyway</T></button>
        <button type="button" className="nb-btn" onClick={() => setPending(null)}><T>Cancel</T></button>
      </p>
    </div> : null}
    {results !== null && results.length === 0 ? <p className="muted"><T>This word is not in the dictionary yet.</T></p> : null}
    {results?.length ? <div className="nbp-results">
      {results.map((entry) => <div key={entry.entryId} className="nbp-result">
        <p className="nbp-result__head">
          <span lang={languageCode}>{entry.headword}</span>
          {entry.level ? <span className="nbp-result__level">{entry.level}</span> : null}
        </p>
        <ul className="nbp-senses">
          {entry.senses.map((sense) => <li key={sense.senseId}>
            <span>
              {sense.partOfSpeech ? <span className="muted">({sense.partOfSpeech}) </span> : null}
              {sense.reading ? <span className="muted">[{sense.reading}] </span> : null}
              {sense.meaning ? <strong>{sense.meaning} </strong> : null}
              {sense.meaning ? <span className="muted">({sense.text})</span> : sense.text}
              {sense.example ? <em className="muted small"> — {sense.example}</em> : null}
            </span>
            <button type="button" className="nb-btn" disabled={save.isPending}
                    onClick={() => save.mutate({ entryId: entry.entryId, senseId: sense.senseId, headword: entry.headword })}>
              <T>Add</T>
            </button>
          </li>)}
        </ul>
        {entry.sourceName ? <small className="dictionary-credit muted">
          <T>Source:</T> {entry.sourceUrl ? <a href={entry.sourceUrl} target="_blank" rel="noopener noreferrer">{entry.sourceName}</a> : entry.sourceName}
          {entry.sourceLicense ? `, ${entry.sourceLicense}` : ""}
        </small> : null}
      </div>)}
    </div> : null}
    {save.isError && !pending ? <p className="error" role="alert">
      {listErrorCode(save.error) === "list_full" ? <T>The notebook is full. Remove a word first.</T> : <T>That word could not be added. Please try again.</T>}
    </p> : null}
  </NotebookDialog>;
}

function searchError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) return tr("Too many lookups. Please wait a moment.");
  return tr("The dictionary could not be searched. Please try again.");
}
