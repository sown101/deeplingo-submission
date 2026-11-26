import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

// The interface language follows the learner's support language (PRD FR-6.1, Q12). English text is the key,
// so a missing Vietnamese entry falls back to the English text and nothing breaks.
export type Translate = (text: string, params?: Record<string, string | number>) => string;

export function fill(text: string, params?: Record<string, string | number>): string {
  return params ? text.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match)) : text;
}

const english: Translate = (text, params) => fill(text, params);
const I18nContext = createContext<Translate>(english);

// For code that runs when something happens (an error message built outside a component). It uses the language the
// provider applied last. Text shown while rendering should use useT() or <T> so it follows the language when it changes.
let active: Translate = english;
export function tr(text: string, params?: Record<string, string | number>): string {
  return active(text, params);
}

export function translatorFor(language: string | null | undefined, catalog: Record<string, string> = {}): Translate {
  if (language?.toLowerCase().startsWith("vi")) return (text, params) => fill(catalog[text] ?? text, params);
  return english;
}

// A stored choice ("en" or "vi") overrides the support language; deterministic browser tests pin English with it.
export const UI_LANGUAGE_KEY = "deeplingo.ui_language";

function storedLanguage(): string | null {
  try {
    const value = window.localStorage.getItem(UI_LANGUAGE_KEY);
    return value === "en" || value === "vi" ? value : null;
  } catch {
    return null;
  }
}

let cachedVi: Record<string, string> | null = null;

export function I18nProvider({ language, children }: { language: string | null | undefined; children: ReactNode }) {
  const effective = storedLanguage() ?? language;
  const wantsVietnamese = Boolean(effective?.toLowerCase().startsWith("vi"));
  const [catalog, setCatalog] = useState<Record<string, string> | null>(() => (wantsVietnamese ? cachedVi : null));

  // The Vietnamese catalog is a separate chunk: learners who study with English support never download it.
  useEffect(() => {
    if (!wantsVietnamese || cachedVi) return;
    let live = true;
    void import("./vi").then((module) => {
      cachedVi = module.VI;
      if (live) setCatalog(module.VI);
    }).catch(() => undefined);
    return () => { live = false; };
  }, [wantsVietnamese]);

  const translate = useMemo(() => translatorFor(effective, catalog ?? {}), [effective, catalog]);
  // Screen readers and the browser's own translation read the page language from the root element.
  useEffect(() => { document.documentElement.lang = wantsVietnamese ? "vi" : "en"; }, [wantsVietnamese]);
  useEffect(() => {
    active = translate;
    return () => { active = english; };
  }, [translate]);
  return <I18nContext.Provider value={translate}>{children}</I18nContext.Provider>;
}

export function useT(): Translate {
  return useContext(I18nContext);
}

/** Text in JSX: `<T>Start</T>` renders the translation of "Start". */
export function T({ children, ...params }: { children: string } & Record<string, string | number>) {
  return <>{useT()(children, params as Record<string, string | number>)}</>;
}
