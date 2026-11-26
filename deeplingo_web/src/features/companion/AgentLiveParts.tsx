import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useContainer } from "../../app/container";
import { T, useT } from "../../i18n/i18n";
import { reviewHref } from "../notebookStudy/studySession";
import type { PlanItemKind } from "../plan/planModels";
import type { AgentAction, CompanionRequest } from "./companionModels";
import type { OpeningChoice, RealtimeHint, TurnPronunciation } from "./realtimeClient";

/** The words of one opening choice, in the interface language. */
export function openingChoiceLabel(t: ReturnType<typeof useT>, choice: OpeningChoice): string {
  return choice.id === "video" ? t("Talk about a video part I studied")
    : choice.id === "words" ? t("Practise {count} words due today", { count: String(choice.count ?? "") })
    : choice.id === "roleplay" ? t("Practise a real situation") : t("Chat about a topic I choose");
}

/** What Tata offers when the learner opened it without a topic: tapping one starts that conversation. */
export function OpeningChoices({ choices, onChoose }: { choices: OpeningChoice[]; onChoose: (choice: OpeningChoice) => void }) {
  const t = useT();
  return <div className="agent-choices" role="group" aria-label={t("What would you like to do?")}>
    {choices.map(choice => <button key={choice.id} type="button" className="dl-btn dl-btn--secondary dl-btn--sm"
      onClick={() => onChoose(choice)}>{openingChoiceLabel(t, choice)}</button>)}
  </div>;
}

/** One compact pronunciation note for a turn: the overall number and the words to say again. */
export function PronunciationNote({ score }: { score: TurnPronunciation }) {
  const t = useT();
  return <span className="agent-pron" aria-label={t("Pronunciation")}>
    <strong>{t("Pronunciation {score}", { score: String(score.overall) })}</strong>
    {score.weak_words.length > 0 ? <span>{t("Say again: {words}", { words: score.weak_words.join(", ") })}</span> : null}
  </span>;
}

/** The one hint card: it grows with the help step (question and words, then a frame, then a model answer). */
export function HintCard({ hint }: { hint: RealtimeHint }) {
  const t = useT();
  const { question, frame, frame_reason, model_sentence, items } = hint;
  return <section className="card agent-hint-card" aria-label={t("Hint")}>
    <strong><T>Hint</T></strong>
    {question ? <p>{question}</p> : null}
    {items.length > 0 ? <p className="small">{items.map(item => item.meaning ? `${item.text} (${item.meaning})` : item.text).join(", ")}</p> : null}
    {frame ? <p>{frame}{frame_reason ? <span className="muted small"> — {frame_reason}</span> : null}</p> : null}
    {model_sentence ? <p className="muted"><T model_sentence={model_sentence}>{"Example: {model_sentence}"}</T></p> : null}
  </section>;
}

/** The rule behind the learner's sentence; AI-written text is marked as not yet checked. */
export function GrammarCard({ grammar }: { grammar: { title?: string | null; explanation: string; example: string | null; rules?: string[]; unverified: boolean } }) {
  const t = useT();
  return <section className="card stack" aria-label={t("Grammar explanation")}>
    <strong>{grammar.title ? grammar.title : <T>Why</T>}</strong>
    <p>{grammar.explanation}</p>
    {grammar.example ? <p className="muted">{grammar.example}</p> : null}
    {grammar.rules && grammar.rules.length > 0 ? <ul>{grammar.rules.map(rule => <li key={rule}>{rule}</li>)}</ul> : null}
    {grammar.unverified ? <p className="muted small"><T>AI explanation, not yet checked.</T></p> : null}
  </section>;
}

/** More natural ways to say the learner's sentence, or ideas for what to say next. */
export function OptionsCard({ kind, items }: { kind: "natural" | "suggestions"; items: { sentence: string; explanation: string }[] }) {
  return <div className="card stack">
    <strong>{kind === "natural" ? <T>More natural ways to say it</T> : <T>Things you could say</T>}</strong>
    <ul>{items.map(item => <li key={item.sentence}><span>{item.sentence}</span><br />
      <span className="muted small">{item.explanation}</span></li>)}</ul>
  </div>;
}

/** The four help buttons the learner can press at any time; each is an explicit request sent to the agent. */
export function HelpRequestButtons({ onRequest, disabled = false }: { onRequest: (request: CompanionRequest) => void; disabled?: boolean }) {
  const t = useT();
  return <div className="agent-live-tools" role="group" aria-label={t("Ask Tata for help")}>
    <button type="button" className="dl-btn dl-btn--primary dl-btn--sm" disabled={disabled} onClick={() => onRequest("hint")}><T>Hint</T></button>
    <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={disabled} onClick={() => onRequest("suggest")}><T>Ideas</T></button>
    <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={disabled} onClick={() => onRequest("explain")}><T>Explain</T></button>
    <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={disabled} onClick={() => onRequest("natural")}><T>Sound natural</T></button>
  </div>;
}

const REVIEW_DISPLAY = { showAnswer: true, images: true, reading: true };
const TASK_LABEL: Record<PlanItemKind, string> = {
  review: "Review due words", conversation: "Talk with Tata", video_practice: "Practise a video",
  my_words: "Practise saved words", add_video: "Add a video",
};

/** Where an opening card goes: a review of exactly the chosen words, or the learner's video at the part. */
export function actionHref(card: Extract<AgentAction, { action: "open_review" | "open_video_region" }>): string {
  return card.action === "open_review"
    ? reviewHref(card.language_code, card.concept_ids, ["choice"], REVIEW_DISPLAY, "/home")
    : `/library/videos/${encodeURIComponent(card.library_item_id)}/watch?region=${encodeURIComponent(card.region_id)}`;
}

/** One card for what the agent did for the learner, the same on the voice screen and in the text conversation.
 * A review or a video part is ready and opens with one tap (nothing navigates by itself, so the conversation is not
 * left by accident); a change to today's tasks is already made and can be undone. */
export function ActionCard({ card }: { card: AgentAction }) {
  return card.action === "today_edited" ? <TodayEditCard card={card} /> : <OpenCard card={card} />;
}

function OpenCard({ card }: { card: Extract<AgentAction, { action: "open_review" | "open_video_region" }> }) {
  const t = useT();
  const review = card.action === "open_review";
  return <section className="card stack" role="status" aria-label={t("Ready for you")}>
    <strong>{review ? t("Words to review: {count}", { count: card.concept_ids.length })
      : card.title ?? t("A part of your video")}</strong>
    <p className="small">{review ? t("A review of exactly the words we picked.") : t("Your video opens at that part.")}</p>
    <Link className="dl-btn dl-btn--primary dl-btn--sm" to={actionHref(card)}>
      {review ? <T>Start review</T> : <T>Open video part</T>}
    </Link>
  </section>;
}

function TodayEditCard({ card }: { card: Extract<AgentAction, { action: "today_edited" }> }) {
  const t = useT();
  const { plan } = useContainer();
  const undo = useMutation({ mutationFn: () => plan.undoEdit(card.item_id, card.change) });
  return <section className="card stack" role="status" aria-label={t("Change to today's tasks")}>
    <strong>{card.change === "added" ? t("Added to today's tasks") : t("Removed from today's tasks")}</strong>
    <p className="small">{t("{task} · {minutes} min", { task: card.title ?? t(TASK_LABEL[card.kind]), minutes: card.minutes })}</p>
    {undo.isSuccess ? <p className="small" role="status"><T>Undone</T></p>
      : <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={undo.isPending} onClick={() => undo.mutate()}><T>Undo</T></button>}
    {undo.isError ? <p className="error small" role="alert"><T>That could not be undone. Please try again.</T></p> : null}
  </section>;
}
