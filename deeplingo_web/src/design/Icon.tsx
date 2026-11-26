const paths = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
  library: "M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zm6 3v6l5-3z",
  notebook: "M4 5.5A2.5 2.5 0 0 1 6.5 3H19a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6.5A2.5 2.5 0 0 1 4 18.5zM8 3v18M12 8h4M12 12h4",
  review: "M8 4h11a2 2 0 0 1 2 2v11M5 8h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z",
  chart: "M5 20v-7M10 20V5M15 20v-9M20 20v-4",
  back: "m14 6-6 6 6 6",
  chevron: "m9 6 6 6-6 6",
  close: "m6 6 12 12M6 18 18 6",
  profile: "M20 21v-2a8 8 0 0 0-16 0v2M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  settings: "M4 7h16M4 17h16M8 4v6M16 14v6",
  logout: "M9 4H4v16h5M9 12h11m-4-4 4 4-4 4",
  search: "m20 20-5-5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z",
  plus: "M12 5v14M5 12h14",
  flame: "M12 3c1 3 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 1-3-1-6 1-9z",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  check: "m5 12 5 5 9-10",
  analyze: "M4 5h16M4 10h10M4 15h6m5-1-3 3 3 3m3-6 3 3-3 3",
  subtitles: "M4 5h16v14H4zM7 10h4M7 14h4M14 10h3M14 14h3",
  scissors: "m8 8 12 12M8 16 20 4M9 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  dictation: "M4 5h10M4 10h7M4 15h4m4 4 2-5 5-5 3 3-5 5-5 2Z",
  mic: "M9 5a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0zM5 11a7 7 0 0 0 14 0M12 18v3M8 21h8",
  questions: "M4 4h16v13H9l-5 4zM9 8a3 3 0 1 1 4 3v1M13 14h.01",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6",
  book: "M4 4h16v16H4zM8 4v16M12 8h4M12 12h4",
  pause: "M8 5v14M16 5v14",
  play: "m8 5 11 7-11 7z",
  trash: "M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7",
} as const;

export function Icon({ name }: { name: keyof typeof paths }) {
  return <IconGlyph d={paths[name]} />;
}

export function IconGlyph({ d, filled = false }: { d: string; filled?: boolean }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke={filled ? undefined : "currentColor"} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>;
}
