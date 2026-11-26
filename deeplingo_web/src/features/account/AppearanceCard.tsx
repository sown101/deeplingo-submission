import { useState } from "react";
import { T, useT } from "../../i18n/i18n";
import { THEME_CHOICES, saveTheme, storedTheme, type ThemeChoice } from "../../design/theme";

const LABEL: Record<ThemeChoice, string> = { system: "Match device", light: "Light", dark: "Dark" };

export function AppearanceCard() {
  const t = useT();
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme);
  function choose(next: ThemeChoice) { setChoice(next); saveTheme(next); }
  return <section className="pf-card" aria-labelledby="appearance-title">
    <h2 id="appearance-title"><T>Appearance</T></h2>
    <div className="pf-box">
      <div className="pf-box__row pf-box__row--wrap">
        <span className="pf-box__label"><T>Colour mode</T></span>
        <div className="pf-pills" role="group" aria-label={t("Appearance")}>
          {THEME_CHOICES.map(value => <button key={value} type="button" className="pf-pill" aria-pressed={choice === value}
            onClick={() => choose(value)}>{t(LABEL[value])}</button>)}
        </div>
      </div>
      <p className="pf-hint"><T>Saved on this device only.</T></p>
    </div>
  </section>;
}
