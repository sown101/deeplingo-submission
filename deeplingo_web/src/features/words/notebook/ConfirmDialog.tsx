import type { ReactNode } from "react";
import { T } from "../../../i18n/i18n";
import { NotebookDialog } from "./NotebookDialog";

export function ConfirmDialog({ title, body, action, busy, error, onConfirm, onClose }: {
  title: string;
  body: ReactNode;
  action: string;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return <NotebookDialog title={title} size="tiny" closable={false} onClose={onClose}>
    <div>{body}</div>
    {error ? <p className="error small" role="alert">{error}</p> : null}
    <div className="nb-m-foot">
      <button type="button" className="nb-btn" onClick={onClose}><T>Cancel</T></button>
      <button type="button" className="nb-btn red" disabled={busy} onClick={onConfirm}>{action}</button>
    </div>
  </NotebookDialog>;
}
