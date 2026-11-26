import { useId, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "../../../design/notebookIcons";
import { useT } from "../../../i18n/i18n";
import { useModalDialog } from "../../../lib/modalA11y";

// A centred dialog (a bottom sheet on phones). Escape, the scrim and the close button all close it.
export function NotebookDialog({ title, label, head, size, className = "", closable = true, onClose, children }: {
  title?: ReactNode;
  label?: string;
  head?: ReactNode;
  size?: "tiny" | "narrow";
  className?: string;
  closable?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const t = useT();
  const titleId = useId();
  const ref = useModalDialog<HTMLDivElement>(onClose);
  return createPortal(
    <div className="nb-scrim nb-in" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={ref} className={["nb-modal", size, className].filter(Boolean).join(" ")} role="dialog" aria-modal="true" tabIndex={-1}
           aria-label={label} aria-labelledby={label ? undefined : titleId}>
        {head ?? <div className="nb-m-head">
          <span id={titleId}>{title}</span>
          {closable ? <button type="button" aria-label={t("Close")} title={t("Close")} onClick={onClose}><Icon name="close" /></button> : null}
        </div>}
        {children}
      </div>
    </div>,
    document.body,
  );
}
