// The learner's colour choice. "system" follows the device; light and dark force one. Stored only in this
// browser, because it describes the screen, not the learner.
export type ThemeChoice = "system" | "light" | "dark";
export const THEME_KEY = "deeplingo.theme";
export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark"];

export function storedTheme(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function saveTheme(choice: ThemeChoice): void {
  applyTheme(choice);
  try {
    if (choice === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, choice);
  } catch {
    // The choice still applies for this visit.
  }
}
