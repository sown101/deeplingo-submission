import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../../design/notebookIcons";
import { T, useT } from "../../i18n/i18n";
import type { ExampleSentence } from "../words/wordsModels";
import { scopeHref } from "./studySession";
import type { NotebookScope } from "./studyTypes";
import "../words/notebook-base.css";
import "./study.css";

export function useEscape(onEscape: () => void, active = true) {
  const latest = useRef(onEscape);
  latest.current = onEscape;
  useEffect(() => {
    if (!active) return;
    const listener = (event: globalThis.KeyboardEvent) => { if (event.key === "Escape") latest.current(); };
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, [active]);
}

/** A modal over the page: Escape or the scrim closes it, Tab stays inside and focus returns when it closes. */
export function StudyDialog({ label, className = "", onClose, children }: {
  label: string; className?: string; onClose: () => void; children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEscape(onClose);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    box.current?.focus();
    return () => before?.focus?.();
  }, []);
  function keepFocus(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab" || !box.current) return;
    const items = [...box.current.querySelectorAll<HTMLElement>("button:not(:disabled),input,textarea,a[href]")];
    if (items.length === 0) return;
    const first = items[0], last = items[items.length - 1], current = document.activeElement;
    if (event.shiftKey && (current === first || current === box.current)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && current === last) { event.preventDefault(); first.focus(); }
  }
  const onScrim = (event: MouseEvent<HTMLDivElement>) => { if (event.target === event.currentTarget) onClose(); };
  return (
    <div className="nb-scrim nb-in" onClick={onScrim}>
      <div ref={box} className={`nb-modal ${className}`} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} onKeyDown={keepFocus}>
        {children}
      </div>
    </div>
  );
}

export function StudySwitch({ label, on, onToggle }: { label: string; on: boolean; onToggle: () => void }) {
  return <button type="button" className="nb-switch" aria-pressed={on} onClick={onToggle}><span>{label}</span><i /></button>;
}

export function SpeedSlider({ speed, onChange }: { speed: number; onChange: (speed: number) => void }) {
  const t = useT();
  return <>
    <div className="nb-lbl"><span><T>Speed</T></span><span>{speed}x</span></div>
    <input className="st-speed" type="range" min={0.5} max={1.25} step={0.25} value={speed} aria-label={t("Reading speed")}
      onChange={(event) => onChange(Number(event.target.value))} />
  </>;
}

/** Back on the left, the title in the middle, and an Options popover on the right when `options` is given. `back` is
 * the scope to return to, or a path. */
export function StudyHeader({ scope, back, title, options }: { scope?: NotebookScope; back?: string; title: string; options?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useEscape(() => setOpen(false), open);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!wrap.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  return (
    <header className="st-bar">
      <Link className="st-pill st-bar-back" to={back ?? scopeHref(scope ?? "all")}><Icon name="back" /><T>Back</T></Link>
      <h1>{title}</h1>
      {options ? (
        <div className="nb-pop-wrap st-bar-opts" ref={wrap}>
          <button type="button" className="st-pill" aria-expanded={open} onClick={() => setOpen(!open)}><T>Options</T><Icon name="more" /></button>
          {open ? <div className="nb-popover"><h3><T>Options</T></h3>{options}</div> : null}
        </div>
      ) : null}
    </header>
  );
}

export function ExampleSource({ example }: { example: ExampleSentence }) {
  if (example.aiGenerated) return <small className="st-source"><T>Example written by AI</T></small>;
  if (!example.sourceName) return null;
  return <small className="st-source"><T>Source:</T> {example.sourceName}{example.licenseName ? `, ${example.licenseName}` : ""}</small>;
}

export function StudyMessage({ children }: { children: ReactNode }) {
  return <div className="st-card st-summary">{children}</div>;
}

export function ScopeState({ isLoading, isError, retry }: { isLoading: boolean; isError: boolean; retry: () => void }) {
  if (isError) return <StudyMessage><p role="alert"><T>Your words could not be loaded.</T></p><button type="button" className="nb-btn main" onClick={retry}><T>Retry</T></button></StudyMessage>;
  if (isLoading) return <StudyMessage><p role="status"><T>Loading your words…</T></p></StudyMessage>;
  return null;
}
