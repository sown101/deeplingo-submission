import { useState } from "react";
import { useContainer } from "../../../app/container";
import { T, useT } from "../../../i18n/i18n";
import { addReports, emptyReport, splitIntoBatches, type ImportReport } from "../listsModels";
import { NotebookDialog } from "./NotebookDialog";

interface Progress {
  done: number;
  total: number;
  report: ImportReport;
  failedAt: number | null; // 1-based batch that could not be sent; null when none failed
}

// Paste words (one per line, an optional meaning after a comma or tab); the server matches each one
// to the dictionary. Lines with several meanings wait for the learner's pick and lines it cannot
// find wait to be dismissed. Nothing here makes a word known.
export function PasteDialog({ listId, onChanged, onClose }: { listId: string; onChanged: () => void; onClose: () => void }) {
  const t = useT();
  const { lists } = useContainer();
  const [text, setText] = useState("");
  const [progress, setProgress] = useState<Progress | null>(null);
  const [running, setRunning] = useState(false);

  // Sends the paste in batches of at most 50 lines, one after another, and stops at the first
  // failure. A batch is safe to send again: words already in the notebook are only counted.
  async function run() {
    const batches = splitIntoBatches(text);
    if (batches.length === 0) return;
    setRunning(true);
    let report = emptyReport();
    let failedAt: number | null = null;
    for (let index = 0; index < batches.length; index += 1) {
      setProgress({ done: index, total: batches.length, report, failedAt: null });
      try {
        report = addReports(report, await lists.importBatch(listId, batches[index]));
      } catch {
        failedAt = index + 1;
        break;
      }
      if (report.listFull) break;
    }
    const done = failedAt === null ? batches.length : failedAt - 1;
    setProgress({ done, total: batches.length, report, failedAt });
    if (failedAt === null) setText("");
    setRunning(false);
    onChanged();
  }

  return <NotebookDialog title={t("Paste many words")} size="narrow" onClose={onClose}>
    <div className="nbp-form">
      <label className="nb-field">
        <T>Paste words, one per line</T>
        <textarea autoFocus value={text} disabled={running} placeholder={t("airport\nrely on\ngive up, to stop trying")} onChange={(event) => setText(event.target.value)} />
      </label>
      <button type="button" className="nb-btn main wide" disabled={!text.trim() || running} onClick={() => void run()}>
        {running ? <T>Adding…</T> : <T>Add words</T>}
      </button>
      {progress ? <ImportSummary progress={progress} running={running} /> : null}
    </div>
  </NotebookDialog>;
}

function ImportSummary({ progress, running }: { progress: Progress; running: boolean }) {
  const t = useT();
  const { report } = progress;
  const parts: string[] = [];
  if (report.matched) parts.push(t("{n} added", { n: report.matched }));
  if (report.ambiguous) parts.push(t("{n} need you to choose a meaning", { n: report.ambiguous }));
  if (report.unresolved) parts.push(t("{n} not found in the dictionary", { n: report.unresolved }));
  if (report.alreadyInList) parts.push(t("{n} already in the notebook", { n: report.alreadyInList }));
  if (report.duplicates) parts.push(t("{n} repeated", { n: report.duplicates }));
  if (report.tooLong) parts.push(t("{n} too long", { n: report.tooLong }));
  if (report.aboveLevel) parts.push(t("{n} above your level", { n: report.aboveLevel }));
  return <div role="status" className="stack">
    {running ? <p className="small"><T v1={Math.min(progress.done + 1, progress.total)} total={progress.total}>{"Batch {v1} of {total}…"}</T></p> : null}
    {!running && progress.failedAt === null ? <p className="small">{parts.length > 0 ? parts.join(" · ") : <T>Nothing new to add.</T>}</p> : null}
    {report.listFull ? <p className="error small" role="alert"><T>The notebook is full. Remove a word to add more.</T></p> : null}
    {!running && progress.failedAt !== null ? <p className="error small" role="alert">
      <T failed={progress.failedAt} total={progress.total}>{"Batch {failed} of {total} could not be sent."}</T>{" "}{parts.length > 0 ? <><T parts={parts.join(" · ")}>{"{parts} so far."}</T>{" "}</> : null}
      <T>Press “Add words” again to continue; words already added are skipped.</T>
    </p> : null}
  </div>;
}
