import { useEffect, useRef, useState } from "react";
import { Icon } from "../../../design/notebookIcons";
import { T, useT } from "../../../i18n/i18n";
import type { ShowOptions, WordOrder } from "./model";

const SWITCHES: { key: keyof ShowOptions; label: string }[] = [
  { key: "word", label: "Word" },
  { key: "reading", label: "Phonetic reading" },
  { key: "meaning", label: "Meaning" },
  { key: "notes", label: "Notes shown in full" },
];

// What each tile shows, how the words are sorted, and the paste-many tool of a notebook.
export function OptionsPopover({ show, onShow, order, onOrder, onPaste }: {
  show: ShowOptions;
  onShow: (show: ShowOptions) => void;
  order: WordOrder;
  onOrder: (order: WordOrder) => void;
  onPaste?: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => { if (!wrap.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);

  const orderButton = (value: WordOrder, label: string) => (
    <button type="button" aria-pressed={order === value} onClick={() => onOrder(value)}>{label}</button>
  );
  return <div className="nb-pop-wrap nbp-opts" ref={wrap}>
    <button type="button" className="nbp-pill" aria-expanded={open} onClick={() => setOpen(value => !value)}><T>Options</T><Icon name="dots" /></button>
    {open ? <div className="nb-popover" role="group" aria-label={t("Options")}>
      <h3><T>Options</T></h3>
      {onPaste ? <>
        <button type="button" className="nb-menu-row" onClick={() => { setOpen(false); onPaste(); }}><Icon name="paste" /><T>Paste many words</T></button>
        <div className="nb-sep" />
      </> : null}
      {SWITCHES.map(({ key, label }) => (
        <button key={key} type="button" className="nb-switch" aria-pressed={show[key]} onClick={() => onShow({ ...show, [key]: !show[key] })}>
          <span>{t(label)}</span><i />
        </button>
      ))}
      <div className="nb-lbl"><span><T>Time</T></span></div>
      <div className="nb-two-btn">{orderButton("newest", t("Newest"))}{orderButton("oldest", t("Oldest"))}</div>
      <div className="nb-lbl"><span><T>Word</T></span></div>
      <div className="nb-two-btn">{orderButton("az", "A-Z")}{orderButton("za", "Z-A")}</div>
    </div> : null}
  </div>;
}
