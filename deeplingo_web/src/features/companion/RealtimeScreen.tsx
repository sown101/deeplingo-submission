import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useContainer } from "../../app/container";
import { MicrophoneError, startPcmRecorder, type PcmRecorder } from "../../lib/audio/pcmRecorder";
import { createPcmPlayer, type PcmPlayer } from "../../lib/audio/pcmPlayer";
import { FollowUpList } from "../plan/FollowUpList";
import { SessionAnalysis } from "./SessionAnalysis";
import { RoleplaySetup } from "./RoleplaySetup";
import type { AnalysisReference } from "./sessionAnalysisModels";
import { localDay, type PlanItem } from "../plan/planModels";
import { OFFER_PATHS, type OfferKind,
  RealtimeSession,
  realtimeUrl,
  type RealtimeCorrection,
  type RealtimeEvent,
  type RealtimeHint,
  type GrammarExplanation,
  type RealtimeSuggestion,
  type SessionSummary,
  type RealtimeLookup,
  type SaveWordOffer,
  type StudyRequestNotice,
  type OpeningChoice,
  type TurnPronunciation,
  speechOnly,
} from "./realtimeClient";
import { ActionCard, GrammarCard, HintCard, OpeningChoices, OptionsCard, PronunciationNote } from "./AgentLiveParts";
import type { AgentAction } from "./companionModels";
import { T, useT, tr } from "../../i18n/i18n";
import { Mascot } from "../../design/Mascot";
import { AgentVoiceStage, type AgentVoicePhase } from "./AgentVoiceStage";
import { entryFrom } from "./agentConversationParams";
import { StudyRequestCard } from "./StudyRequestCard";
import { TranscriptConsentPrompt } from "./TranscriptConsentPrompt";

interface Line {
  role: "learner" | "companion";
  text: string;
}

type Card =
  | { kind: "suggestions"; items: RealtimeSuggestion[] }
  | { kind: "natural"; items: RealtimeSuggestion[] }
  | { kind: "grammar"; grammar: GrammarExplanation }
  | { kind: "correction"; correction: RealtimeCorrection }
  | { kind: "lookup"; lookup: RealtimeLookup }
  | { kind: "study_request"; request: StudyRequestNotice }
  | { kind: "save_word"; offer: SaveWordOffer }
  | { kind: "action"; card: AgentAction };

const OFFER_LABEL: Record<OfferKind, string> = { review: "Review", grammar: "Grammar", notebook: "Notebook" };

const SEND_INTERVAL_MS = 100;

export function realtimeErrorMessage(code: string): string {
  switch (code) {
    case "realtime_not_available":
      return tr("Reflex practice is not open for this account yet.");
    case "realtime_limit":
      return tr("You have reached today's reflex practice time. Try the regular conversation.");
    case "realtime_unavailable":
      return tr("Reflex practice is unavailable right now. Try the regular conversation.");
    case "authentication_required":
      return tr("Sign in again to start.");
    case "companion_no_items":
      return tr("Watch and prepare a video first, then come back to practise.");
    case "voice_consent_required":
      return tr("Allow voice processing in Profile to talk with the agent.");
    case "companion_topic_not_found":
      return tr("That topic is no longer in your notebooks. Choose another.");
    case "companion_video_not_found":
      return tr("This video is no longer in your Library.");
    case "companion_video_not_ready":
      return tr("This video is not ready for conversation yet.");
    case "language_profile_required":
      return tr("Choose your learning language first.");
    default:
      return tr("Reflex practice could not start. Please try again.");
  }
}

const END_REASON: Record<string, string> = {
  learner_ended: "You ended the conversation.",
  time_limit: "Time is up for this conversation.",
  consent_revoked: "The conversation ended because voice processing was turned off.",
  policy: "The conversation was stopped because a reply broke the practice rules.",
  provider_closed: "The connection to the companion closed.",
  invalid_audio: "The microphone sent audio we could not use.",
};


// Transcription arrives in pieces; consecutive pieces from the same speaker form one line.
function appendLine(lines: Line[], role: Line["role"], text: string): Line[] {
  const last = lines[lines.length - 1];
  if (last && last.role === role && !last.text.endsWith("\n")) {
    return [...lines.slice(0, -1), { role, text: last.text + text }];
  }
  return [...lines, { role, text: text.trimStart() }];
}

/** The lines a learner may read: speech only, so a marker or a silence never shows as a line. */
function visibleLines(lines: Line[]): Line[] {
  return lines.flatMap(line => {
    const text = speechOnly(line.text);
    return text.trim() ? [{ ...line, text }] : [];
  });
}

/** The agent on the watch screen: it talks about the part being watched, and the video waits for the learner. */
export interface WatchingVideo {
  item: string;
  /** The transcript part playing when the learner presses talk. */
  segmentId: () => string | null;
  /** Pressing talk pauses the video; it is not resumed until the learner says so. */
  onTalk: () => void;
}

export function RealtimeScreen({ watching, fullPage = false, topicPicker = false, compact = false, onPhaseChange, onMicError, context, onFallback, onTextChat, onTopicChange }: { watching?: WatchingVideo; fullPage?: boolean; topicPicker?: boolean; compact?: boolean; onPhaseChange?: (phase: AgentVoicePhase) => void; onMicError?: (blocked: boolean) => void; context?: { entry: "video" | "home" | "review"; item: string | null; topicId?: string }; onFallback?: () => void; onTextChat?: () => void; onTopicChange?: (topicId: string) => void }) {
  const t = useT();
  const [params] = useSearchParams();
  const selected = watching ? { entry: "video" as const, item: watching.item } : context ?? entryFrom(params);
  const { config, gateway, companion, lists, words, onboarding } = useContainer();
  const queryClient = useQueryClient();
  // Subscribed, so the saved words follow the profile once it has loaded.
  const profileQuery = useQuery({ queryKey: ["language-profile"], queryFn: () => onboarding.loadProfile(), retry: false });
  const language = profileQuery.data?.learning_language ?? undefined;
  const previewWords = useQuery({ queryKey: ["agent", "saved-words", language, selected?.item],
    queryFn: () => words.list(language, selected?.item ?? undefined), enabled: fullPage, retry: false });
  // The learner's one voice consent is read before any conversation; the server enforces it as well.
  const consentQuery = useQuery({ queryKey: ["agent-consent"], queryFn: () => companion.getAgentConsent(), retry: false });
  const allow = useMutation({
    mutationFn: () => companion.setAgentConsent(true),
    onSuccess: (consent) => queryClient.setQueryData(["agent-consent"], consent),
  });
  const granted = consentQuery.data?.status === "granted";
  // Free conversation only: the agent picks the words, the learner may change the topic.
  const [topicId, setTopicId] = useState(context?.topicId ?? params.get("topic") ?? "");
  const [scenarioId, setScenarioId] = useState(params.get("scenario") ?? "hotel");
  const [swapRoles, setSwapRoles] = useState(params.get("swap") === "1");
  const scenarios = useQuery({ queryKey: ["agent-scenarios"], queryFn: () => companion.scenarios(), enabled: topicPicker, retry: false });
  const scenarioReady = !topicPicker || scenarios.data?.some(item => item.id === scenarioId) === true;
  const wantsTopic = !watching && selected?.entry === "home";
  const notebooks = useQuery({ queryKey: ["agent-topics"], queryFn: () => lists.list(), retry: false, enabled: wantsTopic });
  const [phase, setPhase] = useState<AgentVoicePhase>("idle");
  useEffect(() => { onPhaseChange?.(phase); }, [phase, onPhaseChange]);
  const [paused, setPaused] = useState(false);
  const muted = useRef(false);
  const serverEnded = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [topic, setTopic] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [cards, setCards] = useState<Card[]>([]);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [ended, setEnded] = useState<{ reason: string; followUps: PlanItem[]; analysis?: AnalysisReference; summary?: SessionSummary } | null>(null);
  const [helpStep, setHelpStep] = useState(0);
  const [hint, setHint] = useState<RealtimeHint | null>(null);
  const [choices, setChoices] = useState<OpeningChoice[]>([]);
  const [pronunciation, setPronunciation] = useState<TurnPronunciation[]>([]);
  const [tasks, setTasks] = useState<PlanItem[]>([]);
  const [offer, setOffer] = useState<OfferKind | null>(null);
  const session = useRef<RealtimeSession | null>(null);
  const recorder = useRef<PcmRecorder | null>(null);
  const player = useRef<PcmPlayer | null>(null);
  const sampleRate = useRef(24_000);
  const timers = useRef<number[]>([]);
  const deadline = useRef(0);
  const attempt = useRef(0);

  function stopMedia() {
    timers.current.forEach((id) => window.clearInterval(id));
    timers.current = [];
    recorder.current?.dispose();
    recorder.current = null;
    player.current?.close();
    player.current = null;
  }

  useEffect(() => () => {
    attempt.current += 1;
    session.current?.close();
    session.current = null;
    stopMedia();
  }, []);

  function onEvent(event: RealtimeEvent) {
    switch (event.type) {
      case "ready":
        setPhase("live");
        setTopic(event.topic);
        deadline.current = Date.now() + event.max_seconds * 1000;
        setRemaining(event.max_seconds);
        timers.current.push(window.setInterval(() => {
          setRemaining(Math.max(0, Math.round((deadline.current - Date.now()) / 1000)));
        }, 1000));
        timers.current.push(window.setInterval(() => {
          const chunk = recorder.current?.takeChunk();
          if (!muted.current && chunk && chunk.length > 0) session.current?.sendAudio(chunk);
        }, SEND_INTERVAL_MS));
        break;
      case "audio_format":
        sampleRate.current = event.sample_rate;
        break;
      case "transcript":
        if (event.role === "learner") {
          setHelpStep(0); // a new question starts the ladder again
          setHint(null);
          setChoices([]);
          watching?.onTalk(); // the video waits while the learner speaks, even if it was started again
        }
        setLines((current) => appendLine(current, event.role, event.text));
        break;
      case "turn_complete":
        setLines((current) => current.map((line, index) =>
          index === current.length - 1 && !line.text.endsWith("\n") ? { ...line, text: `${line.text}\n` } : line));
        break;
      case "interrupted":
        player.current?.flush();
        break;
      case "tasks":
        setTasks(event.items);
        break;
      case "offer":
        setOffer(event.kind);
        break;
      case "roleplay":
        setTopic(event.title);
        break;
      case "hint":
        setHint(event.hint); // one card that grows: each step replaces the one before
        setHelpStep(event.hint.level);
        break;
      case "choices":
        setChoices(event.items);
        break;
      case "pronunciation":
        setPronunciation((current) => [...current.filter(item => item.turn !== event.score.turn), event.score]);
        break;
      case "suggestions":
        setCards((current) => [...current, { kind: "suggestions", items: event.items }]);
        break;
      case "natural":
        setCards((current) => [...current, { kind: "natural", items: event.items }]);
        break;
      case "grammar":
        setCards((current) => [...current, { kind: "grammar", grammar: event.grammar }]);
        break;
      case "correction":
        setCards((current) => [...current, { kind: "correction", correction: event.correction }]);
        break;
      case "looked_up":
        setCards((current) => [...current, { kind: "lookup", lookup: event.lookup }]);
        break;
      case "study_request":
        setCards((current) => [...current, { kind: "study_request", request: event.request }]);
        break;
      case "save_word":
        setCards((current) => [...current, { kind: "save_word", offer: event.offer }]);
        break;
      case "action":
        setCards((current) => [...current, { kind: "action", card: event.card }]);
        break;
      case "ended":
        serverEnded.current = true;
        setEnded({ reason: event.reason, followUps: event.follow_ups, analysis: event.analysis,
          summary: event.summary });
        setPhase("ended");
        setHint(null);
        setChoices([]);
        stopMedia();
        break;
      case "error":
        setError(realtimeErrorMessage(event.code));
        setPhase("failed");
        stopMedia();
        break;
    }
  }

  async function start() {
    if (!selected || !scenarioReady) return;
    const currentAttempt = ++attempt.current;
    const isCurrent = () => attempt.current === currentAttempt;
    const segmentId = watching?.segmentId() ?? (selected?.entry === "video" ? params.get("segment") : null);
    watching?.onTalk();
    session.current?.close();
    session.current = null;
    stopMedia();
    setError(null);
    onMicError?.(false);
    setLines([]);
    setCards([]);
    setHint(null);
    setChoices([]);
    setPronunciation([]);
    setHelpStep(0);
    setTasks([]);
    setOffer(null);
    setEnded(null);
    setPhase("connecting");
    serverEnded.current = false;
    muted.current = false;
    setPaused(false);
    try {
      const auth = await gateway.currentSession();
      if (!isCurrent()) return;
      if (!auth) {
        setError(realtimeErrorMessage("authentication_required"));
        setPhase("failed");
        return;
      }
      // Start the player inside the click so the browser allows playback.
      player.current = createPcmPlayer();
      const capture = await startPcmRecorder(undefined, { streaming: true });
      // Permission may resolve after leaving the page or choosing different words.
      if (!isCurrent()) {
        capture.dispose();
        return;
      }
      recorder.current = capture;
      const live = new RealtimeSession(realtimeUrl(config.apiBaseUrl), {
        onEvent: (event) => { if (isCurrent()) onEvent(event); },
        onAudio: (samples) => { if (isCurrent()) player.current?.enqueue(samples, sampleRate.current); },
        onClosed: () => {
          if (!isCurrent()) return;
          session.current = null;
          stopMedia();
          if (serverEnded.current) {
            setPhase("ended");
            return;
          }
          setPhase((current) => {
            if (current === "connecting" || current === "live") {
              setError((existing) => existing ?? realtimeErrorMessage("realtime_unavailable"));
              return "failed";
            }
            return current;
          });
        },
      });
      session.current = live;
      live.open(auth.accessToken, { entry: selected.entry, library_item_id: selected.item, day: localDay(),
        ...(topicId && wantsTopic ? { topic_id: topicId } : {}), ...(segmentId ? { segment_id: segmentId } : {}),
        ...(topicPicker ? { scenario_id: scenarioId, swap_roles: swapRoles } : {}) });
    } catch (cause) {
      if (!isCurrent()) return;
      stopMedia();
      if (cause instanceof MicrophoneError) onMicError?.(true);
      setError(cause instanceof MicrophoneError
        ? cause.kind === "denied"
          ? "Allow microphone access to practise speaking."
          : "No microphone is available in this browser."
        : realtimeErrorMessage("realtime_unavailable"));
      setPhase("failed");
    }
  }

  // Opening the agent starts the conversation; the first time, the consent above comes first.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (!fullPage || topicPicker || autoStarted.current || !granted || phase !== "idle" || !scenarioReady) return;
    autoStarted.current = true;
    void start();
    // start only reads state that is settled when this runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullPage, topicPicker, granted, phase, scenarioReady]);

  if (!selected) {
    return (
      <div className="stack">
        <h1><T>Reflex practice</T></h1>
        <p className="error" role="alert"><T>This conversation link is not valid.</T></p>
        <Link to="/home" className="dl-btn dl-btn--secondary"><T>Back home</T></Link>
      </div>
    );
  }

  const live = phase === "live";
  const shownLines = visibleLines(lines);
  const permissions = <>
      {topicPicker && !live ? <>
        {scenarios.isPending ? <p role="status"><T>Loading situations…</T></p> : null}
        {scenarios.isError ? <div role="alert"><T>Situations could not be loaded.</T><button className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => void scenarios.refetch()}><T>Retry</T></button></div> : null}
        {scenarios.data ? <RoleplaySetup scenarios={scenarios.data} value={scenarioId} swapped={swapRoles} onScenario={setScenarioId} onSwap={setSwapRoles} /> : null}
      </> : null}
      {consentQuery.isError ? (
        <div role="alert">
          <p><T>Your voice settings could not be loaded.</T></p>
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => void consentQuery.refetch()}><T>Retry voice settings</T></button>
        </div>
      ) : null}
      {!live && !granted && consentQuery.data ? (
        <div className="card stack">
          <p>
            <T>Voice conversations need your permission once. The agent processes your speech briefly, including sending audio to a speech service to score pronunciation, and does not store audio. You can switch this off any time in Profile.</T>
          </p>
          <button type="button" className="dl-btn dl-btn--primary" disabled={allow.isPending} onClick={() => allow.mutate()}><T>Allow voice processing</T></button>
          {allow.isError ? <p className="error small" role="alert"><T>That could not be saved. Please try again.</T></p> : null}
        </div>
      ) : null}
      {!live && onTextChat ? <button type="button" className="dl-btn dl-btn--secondary"
        onClick={() => { stopMedia(); session.current?.close(); onTextChat(); }}><T>Text chat</T></button> : null}
      {phase === "idle" && granted ? <TranscriptConsentPrompt /> : null}
      {wantsTopic && (!fullPage || topicPicker) && !live && granted && notebooks.data && notebooks.data.length > 0 ? (
        <label className="stack tight"><T>Topic</T>
          <select value={topicId} onChange={(event) => { setTopicId(event.target.value); onTopicChange?.(event.target.value); }}>
            <option value="">{t("Chosen for you")}</option>
            {notebooks.data.map((book) => <option key={book.id} value={book.id}>{book.name}</option>)}
          </select>
        </label>
      ) : null}

  </>;
  // The hint card and latest help card are shown once on the stage in the full page, so its details list leaves them out.
  const feedback = (withHint: boolean, omitStageCards = false) => {
    const stageCardCount = omitStageCards && cards.length > 0
      ? (cards.at(-1)?.kind === "study_request" && cards.length > 1 ? 2 : 1)
      : 0;
    const detailCards = stageCardCount > 0 ? cards.slice(0, -stageCardCount) : cards;
    return <>
      {(withHint && hint) || detailCards.length > 0 ? (
        <section className="stack" aria-label={t("Help from the companion")}>
          {withHint && hint ? <HintCard hint={hint} /> : null}
          {detailCards.map((card, index) => <HelpCard key={index} card={card} />)}
        </section>
      ) : null}

      {shownLines.length > 0 ? (
        <section className="stack agent-transcript" aria-label={t("Transcript")} aria-live="polite">
          {shownLines.map((line, index) => {
            const turn = line.role === "learner" ? shownLines.slice(0, index + 1).filter(item => item.role === "learner").length : 0;
            const score = pronunciation.find(item => item.turn === turn);
            return <div key={index} className={`agent-line agent-line--${line.role === "learner" ? "me" : "tata"}`}>
              <span className="agent-line__who">{line.role === "learner" ? <T>You</T> : "Tata"}</span>
              <p className="agent-bubble">{line.text.trim()}</p>
              {score ? <PronunciationNote score={score} /> : null}
            </div>;
          })}
        </section>
      ) : null}

      {ended ? (
        <section className="stack">
          <p>{END_REASON[ended.reason] ? t(END_REASON[ended.reason]) : <T>The conversation has ended.</T>}</p>
          {ended.summary ? <SummaryCard summary={ended.summary} /> : null}
          <FollowUpList items={ended.followUps} />
          {ended.analysis ? <SessionAnalysis analysis={ended.analysis} /> : null}
          {selected.entry === "video" && params.get("scope") === "video" ?
            <Link className="dl-btn dl-btn--secondary" to={`/library/videos/${selected.item}/watch`}
                  ><T>Watch this video</T></Link> : null}
        </section>
      ) : null}  </>;
  };
  if (fullPage) {
    const saved = previewWords.data?.words.filter(word => word.saved && word.status === "active").slice(0, 5) ?? [];
    // The latest help card; a notebook notice keeps the correction it came from in view.
    const [previousCard, latestCard] = [cards.at(-2), cards.at(-1)];
    const activeHint = helpStep > 0 ? hint : null;
    const hintWord = activeHint?.items[0]?.text ?? null;
    const latestScore = pronunciation.at(-1);
    return <AgentVoiceStage phase={phase} paused={paused} remaining={remaining} words={saved}
      wordsLoading={previewWords.isPending} wordsFailed={previewWords.isError}
      permissions={permissions} actions={!ended && (tasks.length || offer) ? <div className="agent-actions">
        <FollowUpList items={tasks} />
        {offer ? <Link className="dl-btn dl-btn--primary" to={OFFER_PATHS[offer]}><T>{OFFER_LABEL[offer]}</T></Link> : null}
      </div> : null} error={error} canStart={granted && !consentQuery.isError && scenarioReady}
      utterance={shownLines.at(-1)?.text.trim() ?? null}
      choices={choices.length > 0 ? <OpeningChoices choices={choices} onChoose={choice => { setChoices([]); session.current?.choose(choice.id); }} /> : null}
      pronunciation={latestScore ? <PronunciationNote score={latestScore} /> : null}
      hintWord={hintWord} helping={activeHint !== null}
      helpCard={activeHint || latestCard ? <>
        {activeHint ? <HintCard hint={activeHint} /> : null}
        {latestCard?.kind === "study_request" && previousCard ? <HelpCard card={previousCard} /> : null}
        {latestCard ? <HelpCard card={latestCard} /> : null}
      </> : null}
      errorActions={onFallback ? <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => { stopMedia(); session.current?.close(); onFallback(); }}><T>Type or record instead</T></button> : null}
      feedback={ended ? <div className="agent-feedback">{feedback(false)}</div> : null}
      helpLabel={t(helpStep === 0 ? "Hint" : helpStep === 1 ? "More help" : "Show a full example")}
      onStart={() => void start()} onPause={() => { muted.current = !muted.current; setPaused(muted.current); }}
      onEnd={() => { stopMedia(); session.current?.end(); }} onHelp={() => session.current?.help()}
      onRetryWords={() => void previewWords.refetch()}
      tools={<>
        <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => session.current?.suggest()}><T>Ideas</T></button>
        <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => session.current?.explain()}><T>Explain</T></button>
        <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => session.current?.natural()}><T>Sound natural</T></button>
        {(cards.length > (cards.at(-1)?.kind === "study_request" && cards.length > 1 ? 2 : 1)) || shownLines.length ? (
          <details><summary><T>Conversation details</T></summary><div className="agent-details-body">{feedback(false, true)}</div></details>
        ) : null}
      </>} />;
  }
  return (
    <div className="stack realtime-screen" data-phase={phase}>
      {!compact ? <div className="realtime-mascot"><Mascot state={ended ? "happy" : live ? "listen" : "idle"} /></div> : null}
      <div className="row between">
        {!compact ? watching ? <h2><T>Talk about this part</T></h2>
          : <h1><T>Talk with your agent</T></h1> : null}
        {live && remaining !== null ? (
          <span className="muted small" aria-label={t("Time left")}>
            {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")}
          </span>
        ) : null}
      </div>
      {topic ? <p className="muted"><T topic={topic}>{"Topic: {topic}"}</T></p> : null}
      {!compact ? <p className="muted small">
        <T>Speak freely and the agent answers right away. Saved words you use correctly can update your word progress; nothing else here changes your scores. Use headphones so the agent does not hear itself.</T>
      </p> : null}

      {error ? <p className="error" role="alert">{t(error)}</p> : null}
      {error && onFallback ? <button type="button" className="dl-btn dl-btn--secondary" onClick={onFallback}><T>Use recorded turns</T></button> : null}

      {permissions}

      <div className="row">
        {live ? (
          <>
            <button type="button" className="dl-btn dl-btn--secondary" onClick={() => session.current?.help()}>
              {helpStep === 0 ? <T>Hint</T> : helpStep === 1 ? <T>More help</T> : <T>Show a full example</T>}</button>
            <button type="button" className="dl-btn dl-btn--secondary" onClick={() => session.current?.suggest()}><T>Ideas</T></button>
            <button type="button" className="dl-btn dl-btn--secondary" onClick={() => session.current?.explain()}><T>Explain</T></button>
            <button type="button" className="dl-btn dl-btn--secondary" onClick={() => session.current?.natural()}><T>Sound natural</T></button>
            <button type="button" className="dl-btn dl-btn--primary" onClick={() => { stopMedia(); session.current?.end(); }}><T>End</T></button>
          </>
        ) : (
          granted ? (
            <button type="button" className="dl-btn dl-btn--primary" disabled={phase === "connecting"} onClick={() => void start()}>
              {phase === "connecting" ? <T>Connecting…</T> : compact ? <T>Start talking</T> : watching ? <T>Talk about this part</T> : phase === "idle" ? <T>Start</T> : <T>Start again</T>}
            </button>
          ) : null
        )}
      </div>

      {live && choices.length > 0 ? <OpeningChoices choices={choices} onChoose={choice => { setChoices([]); session.current?.choose(choice.id); }} /> : null}
      {feedback(true)}
    </div>
  );
}

function SummaryCard({ summary }: { summary: SessionSummary }) {
  const t = useT();
  return (
    <section className="card stack" aria-label={t("Session summary")}>
      <strong><T>Session summary</T></strong>
      <p>{summary.spoken_turns === 1 ? <T n={1}>{"You spoke {n} time."}</T> : <T n={summary.spoken_turns}>{"You spoke {n} times."}</T>}</p>
      <p className="small muted">
        {summary.corrections === 1 ? <T n={1}>{"{n} correction"}</T> : <T n={summary.corrections}>{"{n} corrections"}</T>}
        {" · "}
        {summary.hints === 1 ? <T n={1}>{"{n} hint"}</T> : <T n={summary.hints}>{"{n} hints"}</T>}
        {" · "}
        {summary.suggestions === 1 ? <T n={1}>{"{n} idea request"}</T> : <T n={summary.suggestions}>{"{n} idea requests"}</T>}
      </p>
      {summary.words_to_reuse.length > 0 ? <p><T v1={summary.words_to_reuse.join(", ")}>{"Words to try again: {v1}"}</T></p> : null}
      {summary.weak_words ? <p><T v1={summary.weak_words.join(", ")}>{"Words to practise saying: {v1}"}</T></p> : null}
      {summary.error_types ? <p><T v1={summary.error_types.map((kind) => kind.replace(/_/g, " ")).join(", ")}>{"Grammar to review: {v1}"}</T></p> : null}
      {summary.grammar_notes ? (
        <>
          <ul className="stack tight">
            {summary.grammar_notes.map((entry) => (
              <li key={entry.code}>{entry.note}{entry.example ? <><br /><span className="muted">{entry.example}</span></> : null}</li>
            ))}
          </ul>
          <p className="muted small"><T>Short notes, not yet reviewed by an editor.</T></p>
        </>
      ) : null}
    </section>
  );
}

function SaveWordCard({ offer }: { offer: SaveWordOffer }) {
  const { words } = useContainer();
  const save = useMutation({ mutationFn: () => words.save({ source: "dictionary", language_code: offer.language_code,
    entry_id: offer.entry_id, sense_id: offer.sense_id }) });
  return (
    <div className="card stack">
      <strong>{offer.headword}</strong>
      {offer.meaning ? <p className="small">{offer.meaning}</p> : null}
      {save.isSuccess ? <p className="small" role="status"><T>Saved to your notebook.</T></p>
        : <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" disabled={save.isPending} onClick={() => save.mutate()}><T>Save to notebook</T></button>}
      {save.isError ? <p className="error small" role="alert"><T>That could not be saved. Please try again.</T></p> : null}
    </div>
  );
}

function HelpCard({ card }: { card: Card }) {
  if (card.kind === "study_request") return <StudyRequestCard request={card.request} />;
  if (card.kind === "save_word") return <SaveWordCard offer={card.offer} />;
  if (card.kind === "action") return <ActionCard card={card.card} />;
  if (card.kind === "grammar") return <GrammarCard grammar={card.grammar} />;
  if (card.kind === "suggestions" || card.kind === "natural") return <OptionsCard kind={card.kind} items={card.items} />;
  if (card.kind === "correction") {
    const { quote, suggestion, note } = card.correction;
    return (
      <div className="card stack">
        <strong><T>Try saying it this way</T></strong>
        <p><s>{quote}</s> → {suggestion}</p>
        <p className="muted small">{note}</p>
      </div>
    );
  }
  const { word, entries } = card.lookup;
  return (
    <div className="card stack">
      <strong>{word}</strong>
      {entries.map((entry, index) => (
        <div key={index} className="small">
          <p>{entry.headword}: {entry.senses.map((sense) => sense.text).join("; ")}</p>
          {entry.source_name ? (
            <p className="muted small">
              <T>Source:</T> {entry.source_url
                ? <a href={entry.source_url} target="_blank" rel="noreferrer noopener">{entry.source_name}</a>
                : entry.source_name}
              {entry.source_license ? ` (${entry.source_license})` : null}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  );
}
