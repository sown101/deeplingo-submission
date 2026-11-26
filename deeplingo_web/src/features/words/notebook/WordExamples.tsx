import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { T, useT, tr } from "../../../i18n/i18n";
import { ApiError } from "../../../lib/api/errors";
import type { ExampleSentence } from "../wordsModels";

function useExamples(conceptId: string) {
  const { words } = useContainer();
  return useQuery({ queryKey: ["word-examples", conceptId], queryFn: () => words.examples(conceptId) });
}

// The dictionary's example when it has one, otherwise a sentence the server
// has AI write and check. The learner sends no content; AI sentences are always labelled.
export function WordExamples({ conceptId }: { conceptId: string }) {
  const { words } = useContainer();
  const queryClient = useQueryClient();
  const examples = useExamples(conceptId);
  const write = useMutation({
    mutationFn: () => words.writeExample(conceptId),
    onSuccess: (found) => queryClient.setQueryData(["word-examples", conceptId], found),
  });
  const items = examples.data ?? [];
  return <div className="nbp-examples">
    {examples.isLoading ? <p role="status" className="small muted"><T>Loading examples…</T></p> : null}
    {examples.isError ? <p role="alert" className="error small"><T>Examples could not be loaded.</T></p> : null}
    {examples.isSuccess ? <>
      <ul className="nbp-example-list">{items.map((item) => <ExampleItem key={item.id} example={item} />)}</ul>
      {items.length === 0 ? <div>
        <p className="small muted"><T>This word has no example yet.</T></p>
        <button type="button" className="nb-btn" disabled={write.isPending} onClick={() => write.mutate()}>
          {write.isPending ? <T>Looking…</T> : <T>Find an example</T>}
        </button>
        {write.isError ? <p role="alert" className="error small">{writeError(write.error)}</p> : null}
      </div> : null}
    </> : null}
  </div>;
}

// The first example under the meaning, as on the Vocabulary tab. Only reads what the Examples tab reads.
export function FirstExample({ conceptId }: { conceptId: string }) {
  const first = useExamples(conceptId).data?.[0];
  return first ? <ul className="nbp-example-list"><ExampleItem example={first} /></ul> : null;
}

function ExampleItem({ example }: { example: ExampleSentence }) {
  const t = useT();
  const { text, startCodepoint: start, endCodepoint: end } = example;
  const chars = Array.from(text);
  const marked = start !== null && end !== null && end <= chars.length;
  return <li className="nbp-example">
    <p className="nbp-example__text">
      {marked ? <>{chars.slice(0, start).join("")}<mark>{chars.slice(start, end).join("")}</mark>{chars.slice(end).join("")}</> : text}
    </p>
    {example.translation ? <p className="small muted">{example.translation}</p> : null}
    {example.aiGenerated ? (
      <small className="muted"><T>Example written by AI</T></small>
    ) : example.sourceName ? (
      <small className="dictionary-credit muted">
        <T>Source:</T> {example.sourceUrl ? <a href={example.sourceUrl} target="_blank" rel="noopener noreferrer">{example.sourceName}</a> : example.sourceName}
        {example.licenseName ? (
          <>, {example.licenseUrl ? <a href={example.licenseUrl} target="_blank" rel="noopener noreferrer">{example.licenseName}</a> : example.licenseName}</>
        ) : null}
        {example.sourceKind === "corpus" ? <>, <T author={example.author ?? t("Tatoeba contributors")}>{"sentence by {author}"}</T></> : null}
      </small>
    ) : null}
  </li>;
}

function writeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) return tr("Too many requests. Please wait a moment.");
  if (error instanceof ApiError && error.status === 422) return tr("This word has no dictionary meaning to write an example for.");
  return tr("An example could not be found right now. Please try again later.");
}
