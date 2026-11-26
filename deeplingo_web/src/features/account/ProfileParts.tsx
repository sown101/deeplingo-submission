import { useId, useState, type ReactNode } from "react";

/** An on/off setting. It reports the change; the caller saves it. */
export function ProfileSwitch({ label, on, disabled = false, onChange }: { label: string; on: boolean; disabled?: boolean; onChange: (on: boolean) => void }) {
  return <button type="button" role="switch" className="pf-switch" aria-checked={on} aria-label={label} disabled={disabled}
    onClick={() => onChange(!on)} />;
}

/** The head of a row: icon, title as its name, a short state as its description. */
function RowHead({ icon, title, subtitle, chevron = true, ...button }: {
  icon: string; title: string; subtitle?: string; chevron?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const titleId = useId();
  const subtitleId = useId();
  return <button type="button" className="pf-row__head" aria-labelledby={titleId} aria-describedby={subtitle ? subtitleId : undefined} {...button}>
    <span className="pf-row__icon" aria-hidden="true">{icon}</span>
    <span className="pf-row__text"><span id={titleId}>{title}</span>{subtitle ? <small id={subtitleId}>{subtitle}</small> : null}</span>
    {chevron ? <span className="pf-row__chevron" aria-hidden="true">›</span> : null}
  </button>;
}

/** A row that opens its content in place. */
export function ProfileRow({ icon, title, subtitle, tone, disabled = false, open: controlled, onToggle, children }: {
  icon: string; title: string; subtitle?: string; tone?: "danger"; disabled?: boolean; open?: boolean; onToggle?: (open: boolean) => void; children: ReactNode;
}) {
  const [own, setOwn] = useState(false);
  const open = controlled ?? own;
  const panel = useId();
  const toggle = () => { const next = !open; setOwn(next); onToggle?.(next); };
  return <div className={`pf-row${tone ? ` pf-row--${tone}` : ""}${open ? " is-open" : ""}`}>
    <RowHead icon={icon} title={title} subtitle={subtitle} aria-expanded={open} aria-controls={panel} disabled={disabled} onClick={toggle} />
    {open ? <div id={panel} className="pf-row__panel">{children}</div> : null}
  </div>;
}

/** A row that runs one action, such as a download. */
export function ProfileActionRow({ icon, title, subtitle, disabled = false, onClick }: {
  icon: string; title: string; subtitle?: string; disabled?: boolean; onClick: () => void;
}) {
  return <div className="pf-row"><RowHead icon={icon} title={title} subtitle={subtitle} disabled={disabled} onClick={onClick} /></div>;
}
