import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { useContainer } from "../../app/container";
import { T, useT } from "../../i18n/i18n";
import "./review.css";

// A language's own name is the same in every interface language.
const LANGUAGE_NAMES: Record<string, string> = { en: "English", zh: "中文", ja: "日本語", ko: "한국어", fr: "Français" };

export const deckName = (code: string) => LANGUAGE_NAMES[code] ?? code.toUpperCase();

/** The notebook's review decks: one per language, like Anki, with what is due now and what is new. */
export function ReviewDecks() {
  const t = useT();
  const { review } = useContainer();
  const decks = useQuery({ queryKey: ["review-decks"], queryFn: () => review.decks(), retry: false });
  if (decks.isError) {
    return <section className="shelf-card" role="alert">
      <p className="error"><T>Your review decks could not be loaded.</T></p>
      <button type="button" className="nb-btn" onClick={() => void decks.refetch()}><T>Retry</T></button>
    </section>;
  }
  if (!decks.data) return <div className="shelf-card" aria-hidden="true"><div className="dl-skel shelf-chart-loading" /></div>;
  return <section className="shelf-card" aria-labelledby="rv-decks-title">
    <h2 id="rv-decks-title" className="shelf-chart-title"><T>Review decks</T></h2>
    {decks.data.length === 0 ? <p className="shelf-muted"><T>Save words to start a deck.</T></p> : null}
    <div className="rv-decks">
      {decks.data.map((deck) => <Link key={deck.languageCode} className="rv-deck" to={`/review/${encodeURIComponent(deck.languageCode)}`}
        aria-label={t("Review {language}: {due} due, {new} new", { language: deckName(deck.languageCode), due: deck.dueCount, new: deck.newCount })}>
        <span><strong lang={deck.languageCode}>{deckName(deck.languageCode)}</strong><br />
          <small>{t("{n} words", { n: deck.totalCount })}</small></span>
        <span><b>{deck.dueCount}</b> <T>due</T> · {deck.newCount} <T>new</T></span>
      </Link>)}
    </div>
  </section>;
}

/** `/review` and the old `/review/quick` open the deck of the language in the learner's profile; the old grammar page
 * (`?mode=grammar`) opens the notebook's Grammar tab. */
export function ReviewRedirect() {
  const { onboarding } = useContainer();
  const [params] = useSearchParams();
  const grammar = params.get("mode") === "grammar";
  const profile = useQuery({ queryKey: ["language-profile"], queryFn: () => onboarding.loadProfile() });
  if (grammar) return <Navigate to="/words/lists?tab=grammar" replace />;
  if (profile.isError) return <Navigate to="/words/lists" replace />;
  if (!profile.data) return <p role="status"><T>Loading your cards…</T></p>;
  return profile.data.learning_language
    ? <Navigate to={`/review/${encodeURIComponent(profile.data.learning_language)}`} replace />
    : <Navigate to="/words/lists" replace />;
}
