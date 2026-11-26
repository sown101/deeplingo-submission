import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import { MicrophoneError, startPcmRecorder, type PcmRecorder } from "../../lib/audio/pcmRecorder";
import { pcmDurationMs } from "../../lib/audio/wav";
import type { CompanionEntry, CompanionRequest, CompanionTurn, PracticeSuggestion } from "./companionModels";
import { T, useT, tr } from "../../i18n/i18n";
import { Mascot } from "../../design/Mascot";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CompanionFeedback } from "./companionModels";
import type { WatchingVideo } from "./RealtimeScreen";
import { StudyRequestCard } from "./StudyRequestCard";
import { SessionAnalysis } from "./SessionAnalysis";
import { ActionCard, GrammarCard, HelpRequestButtons, openingChoiceLabel, OpeningChoices, OptionsCard } from "./AgentLiveParts";

export type CompanionPhase = "ready" | "starting" | "idle" | "recording" | "thinking" | "finished" | "failed";

const MAX_UTTERANCE_MS = 15_000;
const MAX_TYPED_CHARS = 300;
const MIN_UTTERANCE_MS = 400;

export function companionErrorMessage(error: unknown): string {
  const code = error instanceof ApiError ? error.detail.code : undefined;
  switch (code) {
    case "voice_consent_required":
      return tr("Allow voice processing in Profile to talk with the agent.");
    case "no_speech_detected":
      return tr("We could not hear you. Check your microphone and try again.");
    case "companion_no_items":
      return tr("Watch and prepare a video first, then come back to talk about it.");
    case "companion_video_not_ready":
      return tr("This video is not ready for conversation yet.");
    case "companion_session_invalid":
      return tr("This conversation has ended. Start a new one.");
    case "language_profile_required":
      return tr("Choose your learning language first.");
    case "speaking_rate_limited":
      return tr("You're talking fast! Wait a few seconds and try again.");
    case "companion_text_invalid":
      return tr("Type a short answer (up to 300 characters).");
    case "companion_turn_unavailable":
      return tr("The companion could not answer. Please say it again.");
    case "companion_help_limit":
      return tr("That is enough help for this conversation.");
    default:
      if (error instanceof ApiError && (error.kind === "network" || error.kind === "timeout")) {
        return tr("Connection problem. Check your network and retry.");
      }
      return tr("The companion is temporarily unavailable. Please try again.");
  }
}

// Reply audio is a convenience: any playback failure leaves the text conversation working.
type Clip = { mime_type: string; base64: string };
type Player = { audio: HTMLAudioElement | null; url: string | null; queue: Clip[]; playing: boolean };

function playClip(clip: Clip, current: Player) {
  try {
    current.audio?.pause();
    if (current.url) URL.revokeObjectURL(current.url);
    current.audio = null;
    current.url = null;
    const bytes = Uint8Array.from(atob(clip.base64), (char) => char.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: clip.mime_type }));
    const audio = new Audio(url);
    current.audio = audio;
    current.url = url;
    current.playing = true;
    const next = () => {
      if (current.audio !== audio) return;
      current.playing = false;
      const following = current.queue.shift();
      if (following) playClip(following, current);
    };
    audio.onended = next;
    audio.onerror = next;
    void audio.play().catch(next);
  } catch {
    // Unsupported audio APIs or blocked playback: the reply text is still shown.
    current.playing = false;
  }
}

/** Plays clips one after another (a streamed reply arrives sentence by sentence). */
function playClips(clips: Clip[], current: Player) {
  stopAudio(current);
  const [first, ...rest] = clips;
  if (!first) return;
  current.queue = rest;
  playClip(first, current);
}

/** The next sentence of a streamed reply: played now, or after the one playing. */
function enqueueClip(clip: Clip, current: Player) {
  if (current.playing) current.queue.push(clip);
  else playClip(clip, current);
}

function stopAudio(current: Player) {
  current.queue = [];
  current.playing = false;
  current.audio?.pause();
}

function playAudio(turn: CompanionTurn, current: Player) {
  if (turn.audio) playClips([turn.audio], current);
}

const TOOL_LABEL: Record<PracticeSuggestion["tool"], string> = {
  dictation: "Dictation",
  shadowing: "Shadowing",
};

// The hint ladder steps (1 question, 2 words, 3 frame, 4 example) the agent filled in for a turn.
function givenHintLevels(hints: CompanionTurn["hints"]): number[] {
  return [hints.question, hints.items.length > 0, hints.frame, hints.model_sentence]
    .flatMap((given, index) => (given ? [index + 1] : []));
}

export interface CompanionConversationProps {
  entry: CompanionEntry;
  item: string | null;
  // Inside the video workspace (M1 S3): starts only when the learner asks, and offers practice
  // suggestions through onPractice instead of leaving the page.
  embedded?: boolean;
  onPractice?: (suggestion: PracticeSuggestion) => void;
  onLeave?: () => void;
  readyActions?: ReactNode;
  onPhaseChange?: (phase: CompanionPhase) => void;
  watching?: WatchingVideo;
  topicId?: string;
  segmentId?: string;
  scenarioId?: string;
  swapRoles?: boolean;
  preferText?: boolean;
}

// The server derives learning evidence when the conversation finishes.
export function CompanionConversation({ entry, item, embedded = false, onPractice, onLeave, readyActions, onPhaseChange, watching, topicId, segmentId, scenarioId, swapRoles, preferText = false }: CompanionConversationProps) {
  const t = useT();
  const { companion } = useContainer();
  const cache = useQueryClient();
  const consent = useQuery({ queryKey: ["agent-consent"], queryFn: () => companion.getAgentConsent(), retry: false });
  const allow = useMutation({ mutationFn: () => companion.setAgentConsent(true),
    onSuccess: value => cache.setQueryData(["agent-consent"], value) });
  const granted = consent.data?.status === "granted";
  const [feedback, setFeedback] = useState<CompanionFeedback | null>(null);
  const autoStarted = useRef(false);
  const [textOnly, setTextOnly] = useState(preferText);
  const [phase, setPhase] = useState<CompanionPhase>(embedded || preferText ? "ready" : "starting");
  useEffect(() => { onPhaseChange?.(phase); }, [phase, onPhaseChange]);
  const [turns, setTurns] = useState<CompanionTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [hintLevel, setHintLevel] = useState(0);
  const [showSupport, setShowSupport] = useState<Record<number, boolean>>({});
  const [elapsedMs, setElapsedMs] = useState(0);
  const [typed, setTyped] = useState("");
  const threadRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const thread = threadRef.current;
    if (thread) thread.scrollTop = thread.scrollHeight;
  }, [turns.length]);
  const recorderRef = useRef<PcmRecorder | null>(null);
  const timerRef = useRef<number | null>(null);
  const generationRef = useRef(0);
  const playerRef = useRef<Player>({ audio: null, url: null, queue: [], playing: false });
  // The speech of streamed replies, by turn, for "Play again"; `clipsTick` re-renders when a part arrives.
  const clipsRef = useRef(new WeakMap<CompanionTurn, Clip[]>());
  const [, setClipsTick] = useState(0);
  /** A streamed turn's speech parts: each plays as it arrives, in order, and is kept for "Play again". */
  const streamAudio = (generation: number) => {
    const clips: Clip[] = [];
    const onAudio = (clip: Clip) => {
      if (generation !== generationRef.current) return;
      clips.push(clip);
      enqueueClip(clip, playerRef.current);
      setClipsTick((tick) => tick + 1);
    };
    return { clips, onAudio };
  };
  const latest = turns[turns.length - 1];
  // The newest open ticket, read when leaving to let the server close the conversation.
  const openTicketRef = useRef<{ ticket: string; spoke: boolean } | null>(null);
  useEffect(() => {
    openTicketRef.current = latest?.session_ticket
      ? { ticket: latest.session_ticket, spoke: turns.some((turn) => turn.learner_transcript !== null) }
      : null;
  }, [latest, turns]);

  const accept = (turn: CompanionTurn) => {
    openTicketRef.current = turn.session_ticket ? { ticket: turn.session_ticket, spoke: turn.turn > 0 } : null;
    setTurns((previous) => [...previous, turn]);
    // The learner hesitated: the server's hint step opens without a tap (1 question and words, 2 frame, 3 example).
    setHintLevel(turn.auto_hint_level ? turn.auto_hint_level + 1 : 0);
    setPhase(turn.finished ? "finished" : "idle");
    if (turn.finished) setFeedback(turn);
    playAudio(turn, playerRef.current);
  };

  async function begin(typedSession = false) {
    if (!typedSession && !granted) return;
    autoStarted.current = true;
    setTextOnly(typedSession);
    const generation = ++generationRef.current;
    setPhase("starting");
    setError(null);
    setTurns([]);
    setFeedback(null);
    try {
      const segment = watching?.segmentId() ?? segmentId;
      const context = { ...(segment ? { segment_id: segment } : {}), ...(topicId ? { topic_id: topicId } : {}),
        ...(scenarioId ? { scenario_id: scenarioId, swap_roles: swapRoles ?? false } : {}),
        ...(typedSession ? { text_only: true } : {}) };
      const turn = await (Object.keys(context).length ? companion.start(entry, item, context) : companion.start(entry, item));
      if (generation === generationRef.current) accept(turn);
    } catch (cause) {
      if (generation !== generationRef.current) return;
      setError(companionErrorMessage(cause));
      setPhase("failed");
    }
  }

  useEffect(() => {
    const player = playerRef.current;
    return () => {
      finishOpenSession();
      generationRef.current += 1;
      // A remount (React StrictMode, or the agent screen falling back here) starts the conversation again.
      autoStarted.current = false;
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
      recorderRef.current?.dispose();
      stopAudio(player);
      if (player.url) URL.revokeObjectURL(player.url);
    };
    // Start once per mount; the parent keys this component by its entry selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (embedded || preferText || autoStarted.current) return;
    if (granted) void begin();
    else setPhase("ready");
    // Auto-start only once, after permission has been obtained; retries are explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [granted, embedded, preferText]);

  async function endConversation() {
    let open = openTicketRef.current;
    if (!open || phase === "thinking") return;
    if (phase === "recording") {
      const turn = await stopRecording();
      if (!turn || turn.finished || !turn.session_ticket) return;
      open = { ticket: turn.session_ticket, spoke: true };
    }
    openTicketRef.current = null;
    const generation = ++generationRef.current;
    recorderRef.current?.dispose(); recorderRef.current = null;
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    stopAudio(playerRef.current);
    setPhase("thinking");
    try {
      const result = await companion.finish(open.ticket);
      if (generation === generationRef.current) { setFeedback(result); setPhase("finished"); }
    } catch (cause) {
      if (generation === generationRef.current) { setError(companionErrorMessage(cause)); setPhase("failed"); }
    }
  }

  // Best effort: ends the server conversation so a consenting learner's notes are kept.
  function finishOpenSession() {
    const open = openTicketRef.current;
    openTicketRef.current = null;
    if (open?.spoke) void companion.finish(open.ticket).catch(() => {});
  }

  function leave() {
    finishOpenSession();
    if (onLeave) {
      onLeave();
      return;
    }
    generationRef.current += 1;
    recorderRef.current?.dispose();
    recorderRef.current = null;
    stopAudio(playerRef.current);
    setTurns([]);
    setError(null);
    setPhase("ready");
  }

  async function startRecording() {
    if (phase !== "idle" || recorderRef.current || !granted || textOnly) return;
    watching?.onTalk();
    setError(null);
    stopAudio(playerRef.current);
    const generation = generationRef.current;
    try {
      const recorder = await startPcmRecorder();
      if (generation !== generationRef.current) {
        recorder.dispose();
        return;
      }
      recorderRef.current = recorder;
    } catch (cause) {
      setError(cause instanceof MicrophoneError && cause.kind === "denied"
        ? tr("Microphone access was blocked. Allow the microphone in your browser settings and try again.")
        : tr("No microphone is available in this browser."));
      return;
    }
    const startedAt = performance.now();
    setElapsedMs(0);
    setPhase("recording");
    timerRef.current = window.setInterval(() => {
      const elapsed = performance.now() - startedAt;
      setElapsedMs(elapsed);
      if (elapsed >= MAX_UTTERANCE_MS) void stopRecording();
    }, 100);
  }

  async function stopRecording() {
    const recorder = recorderRef.current;
    if (!recorder) return;
    recorderRef.current = null;
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
    const samples = recorder.stop();
    recorder.dispose();
    const ticket = latest?.session_ticket;
    if (!ticket || pcmDurationMs(samples) < MIN_UTTERANCE_MS) {
      setError(ticket ? tr("That was very short. Hold on a little longer while you speak.") : null);
      setPhase("idle");
      return;
    }
    const generation = generationRef.current;
    setPhase("thinking");
    try {
      const speech = streamAudio(generation);
      const turn = await companion.turn(ticket, samples, speech.onAudio);
      if (generation === generationRef.current) { clipsRef.current.set(turn, speech.clips); accept(turn); return turn; }
    } catch (cause) {
      if (generation !== generationRef.current) return;
      setError(companionErrorMessage(cause));
      // The same ticket stays valid after a failed turn, so the learner can simply retry.
      setPhase(cause instanceof ApiError && cause.detail.code === "companion_session_invalid" ? "finished" : "idle");
    }
  }

  async function sendText(answer: string) {
    const ticket = latest?.session_ticket;
    if (!answer || !ticket || phase !== "idle") return;
    const generation = generationRef.current;
    setError(null);
    setPhase("thinking");
    try {
      const speech = streamAudio(generation);
      const turn = await companion.turnText(ticket, answer.slice(0, MAX_TYPED_CHARS), textOnly ? undefined : speech.onAudio);
      if (generation === generationRef.current) { clipsRef.current.set(turn, speech.clips); setTyped(""); accept(turn); }
    } catch (cause) {
      if (generation !== generationRef.current) return;
      setError(companionErrorMessage(cause));
      setPhase(cause instanceof ApiError && cause.detail.code === "companion_session_invalid" ? "finished" : "idle");
    }
  }

  // A help button is an explicit request: the agent answers it with the matching help, with the typed words or without.
  async function sendRequest(request: CompanionRequest) {
    const ticket = latest?.session_ticket;
    if (!ticket || phase !== "idle") return;
    const generation = generationRef.current;
    setError(null);
    setPhase("thinking");
    try {
      const speech = streamAudio(generation);
      const turn = await companion.turnRequest(ticket, request, typed.trim().slice(0, MAX_TYPED_CHARS) || undefined,
        textOnly ? undefined : speech.onAudio);
      if (generation === generationRef.current) { clipsRef.current.set(turn, speech.clips); setTyped(""); accept(turn); }
    } catch (cause) {
      if (generation !== generationRef.current) return;
      setError(companionErrorMessage(cause));
      setPhase(cause instanceof ApiError && cause.detail.code === "companion_session_invalid" ? "finished" : "idle");
    }
  }

  function sendTyped(event: FormEvent) {
    event.preventDefault();
    void sendText(typed.trim());
  }

  // Only what the agent gave: no hint step is offered or opened when its content is empty.
  const givenHints = latest ? givenHintLevels(latest.hints) : [];
  const nextHintLevel = givenHints.find((level) => level > hintLevel);

  const Heading = embedded ? "h2" : "h1";
  return (
    <div className={embedded ? "companion-conversation embedded" : "companion-conversation"} data-phase={phase}>
      {!textOnly && consent.isPending ? <p role="status"><T>Loading agent settings…</T></p> : null}
      {!textOnly && consent.isError ? <div role="alert"><T>Your agent settings could not be loaded.</T><button className="dl-btn dl-btn--plain" onClick={() => void consent.refetch()}><T>Retry agent settings</T></button></div> : null}
      {!textOnly && consent.isSuccess && !granted ? <div className="dl-card stack">
        <p><T>Voice conversations need your permission once. The agent processes your speech briefly, including sending audio to a speech service to score pronunciation, and does not store audio. You can switch this off any time in Profile.</T></p>
        <button className="dl-btn dl-btn--primary" disabled={allow.isPending} onClick={() => allow.mutate()}><T>Allow voice processing</T></button>
        {allow.isError ? <p role="alert"><T>That change could not be saved. Please try again.</T></p> : null}
      </div> : null}
      {!embedded ? <>
      <div className="row between">
        {/* The agent screen's mode switch already names this screen; the heading stays for screen readers. */}
        <Heading className="sr-only">{embedded ? <T>Companion</T> : <T>Talk with your companion</T>}</Heading>
        {latest ? <span className="muted small"><T turn={latest.turn} max_turns={latest.max_turns}>{"Turn {turn} of {max_turns}"}</T></span> : null}
      </div>
      {latest ? <p className="muted"><T topic={latest.topic}>{"Topic: {topic}"}</T></p> : null}
      {textOnly ? null : <p className="muted small">
        <T>Saved words you use correctly can update your word progress.</T>
        {embedded ? null : (
          <>
            {" · "}
            <Link to={`/agent?mode=voice&entry=${entry}${item ? `&item=${item}` : ""}`}><T>Reflex practice (trial)</T></Link>
          </>
        )}
      </p>}

      </> : null}
      {phase === "ready" ? (
        <div className={embedded ? "ag-choices" : "workspace-card"}>
          {!embedded && !preferText ? <p className="muted"><T>Talk about your study part: what happens in it and your own experience.</T></p> : null}
          {readyActions}
          {!preferText ? <button type="button" disabled={!granted} className={embedded ? "dl-chip dl-chip--neutral" : "dl-btn dl-btn--primary"} onClick={() => void begin()}>
            {embedded ? <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-3.1A7 7 0 0 0 19 11z" /></svg> : null}
            <T>Start talking</T>
          </button> : null}
          <div className="stack tight">
            <p className="muted small"><T>The AI processes what you type to respond. DeepLingo keeps the messages temporarily for this conversation.</T></p>
            <button type="button" className="dl-btn dl-btn--secondary" onClick={() => void begin(true)}><T>Start text chat</T></button>
          </div>
        </div>
      ) : null}

      <div className="companion-layout">
        <div className="companion-thread" ref={threadRef}>
          <ol className="companion-log" aria-live="polite">
            {turns.map((turn, index) => (
              <li key={index} className="companion-turn">
                {turn.learner_transcript ? (
                  <div className="bubble learner">
                    <span className="sr-only"><T>You said:</T> </span>{turn.learner_transcript}
                  </div>
                ) : null}
                {turn.correction ? (
                  <div className="bubble correction">
                    <span className="strike">{turn.correction.quote}</span> → <strong>{turn.correction.suggestion}</strong>
                    <span className="small">{turn.correction.note}</span>
                  </div>
                ) : null}
                {turn.looked_up.map((word) => (
                  <div key={word.headword} className="bubble lookup" aria-label={`Dictionary: ${word.headword}`}>
                    <strong>{word.headword}</strong>
                    <ul className="small">
                      {word.senses.slice(0, 3).map((sense, i) => (
                        <li key={i}>{sense.part_of_speech ? <em>{sense.part_of_speech} </em> : null}{sense.text}</li>
                      ))}
                    </ul>
                    {word.source_name ? (
                      <span className="small muted">
                        <T>Source:</T>{" "}
                        {word.source_url ? (
                          <a href={word.source_url} target="_blank" rel="noopener noreferrer">{word.source_name}</a>
                        ) : (
                          word.source_name
                        )}
                        {word.source_license ? `, ${word.source_license}` : ""}
                      </span>
                    ) : null}
                  </div>
                ))}
                {turn.used_items.length > 0 ? (
                  <p className="small used-items"><T v1={turn.used_items.map((used) => used.text).join(", ")}>{"Nice! You used: {v1}"}</T></p>
                ) : null}
                <div className="bubble companion">
                  <span lang={turn.language_code}>{turn.reply}</span>
                  {showSupport[index] ? <span className="support small" lang={turn.support_language_code}>{turn.reply_support}</span> : null}
                  <span className="row bubble-actions">
                    {turn.audio || clipsRef.current.get(turn)?.length ? (
                      <button type="button" className="dl-btn dl-btn--plain dl-btn--sm" onClick={() => (turn.audio
                        ? playAudio(turn, playerRef.current) : playClips(clipsRef.current.get(turn) ?? [], playerRef.current))}>
                        <T>Play again</T>
                      </button>
                    ) : null}
                    <button type="button" className="dl-btn dl-btn--plain dl-btn--sm"
                      aria-pressed={!!showSupport[index]}
                      onClick={() => setShowSupport((previous) => ({ ...previous, [index]: !previous[index] }))}>
                      <T>Vietnamese</T>
                    </button>
                  </span>
                </div>
                {turn.grammar ? <GrammarCard grammar={turn.grammar} /> : null}
                {turn.natural.length > 0 ? <OptionsCard kind="natural" items={turn.natural} /> : null}
                {turn.suggestions.length > 0 ? <OptionsCard kind="suggestions" items={turn.suggestions} /> : null}
                {turn.study_request ? <StudyRequestCard request={turn.study_request} /> : null}
                {turn.actions.map((card, position) => <ActionCard key={position} card={card} />)}
                {index === turns.length - 1 && turn.choices.length > 0 && turn.session_ticket && phase === "idle"
                  ? <OpeningChoices choices={turn.choices} onChoose={choice => void sendText(openingChoiceLabel(t, choice))} /> : null}
                {turn.practice_suggestion && onPractice ? (
                  <div className="bubble suggestion" aria-label={t("Practice suggestion")}>
                    <span className="small" lang={turn.support_language_code}>{turn.practice_suggestion.reason}</span>
                    <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm"
                      onClick={() => onPractice(turn.practice_suggestion!)}>
                      <T v1={t(TOOL_LABEL[turn.practice_suggestion.tool])}>{"Open {v1}"}</T>
                    </button>
                  </div>
                ) : null}
              </li>
            ))}
          </ol>

          {phase === "starting" ? <p role="status"><T>Starting the conversation…</T></p> : null}
          {phase === "thinking" ? <p role="status"><T>Listening and thinking…</T></p> : null}
          {error ? <p className="error" role="alert">{error}</p> : null}
        </div>

        {phase !== "ready" ? (
          <aside className="companion-stage" data-phase={phase} aria-label={t("Conversation controls")}>
            <Mascot state={phase === "finished" ? "happy" : phase === "recording" ? "listen" : "idle"} className="conversation-mascot" />
            {latest && !latest.finished && (phase === "idle" || phase === "recording") && givenHints.length > 0 ? (
              <section className="companion-hints" aria-label={t("Hints")}>
                {hintLevel >= 1 && latest.hints.question ? <p>{latest.hints.question}</p> : null}
                {hintLevel >= 2 && latest.hints.items.length > 0 ? (
                  <ul className="hint-items">
                    {latest.hints.items.map((hint) => (
                      <li key={hint.id}><strong>{hint.text}</strong>{hint.meaning ? ` — ${hint.meaning}` : ""}</li>
                    ))}
                  </ul>
                ) : null}
                {hintLevel >= 3 && latest.hints.frame ? (
                  <p><strong lang={latest.language_code}>{latest.hints.frame.frame}</strong><br />
                    <span className="small muted">{latest.hints.frame.reason}</span></p>
                ) : null}
                {hintLevel >= 4 && latest.hints.model_sentence ? (
                  <p><span lang={latest.language_code}>{latest.hints.model_sentence}</span><br />
                    <span className="small muted"><T>Now say it in your own words.</T></span></p>
                ) : null}
                {nextHintLevel !== undefined ? (
                  <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => setHintLevel(nextHintLevel)}>
                    {hintLevel === 0 ? <T>Need a hint?</T> : <T>Another hint</T>}
                  </button>
                ) : null}
              </section>
            ) : null}

            {phase === "idle" && latest?.session_ticket ? (
              <form className="row companion-type" onSubmit={sendTyped}>
                <input type="text" value={typed} maxLength={MAX_TYPED_CHARS} lang={latest.language_code}
                  aria-label={t("Type your answer")} placeholder={t("Type your answer")}
                  onChange={(event) => setTyped(event.target.value)} />
                <button type="submit" className="dl-btn dl-btn--secondary" disabled={!typed.trim()}><T>Send</T></button>
              </form>
            ) : null}
            {phase === "idle" && latest?.session_ticket ? <HelpRequestButtons onRequest={(request) => void sendRequest(request)} /> : null}
            <div className="row companion-controls">
              {phase === "idle" && !textOnly && granted ? (
                <button type="button" className="dl-btn dl-btn--primary" onClick={() => void startRecording()}>
                  <T>Tap to speak</T>
                </button>
              ) : null}
              {phase === "recording" ? (
                <button type="button" className="dl-btn dl-btn--primary recording" onClick={() => void stopRecording()}>
                  <T v1={Math.ceil((MAX_UTTERANCE_MS - elapsedMs) / 1000)}>{"Tap to send ({v1}s)"}</T>
                </button>
              ) : null}
              {/* M1 Q1: study-plan follow-ups are not offered on web. */}
              {phase === "finished" || phase === "failed" ? (
                <button type="button" className="dl-btn dl-btn--primary" onClick={() => void begin(textOnly)}>
                  <T>Start a new conversation</T>
                </button>
              ) : null}
              {!embedded && latest?.session_ticket && phase === "idle" ? <button type="button" className="dl-btn dl-btn--secondary" onClick={() => void endConversation()}><T>End conversation</T></button> : null}
              <button type="button" disabled={embedded && (phase === "thinking" || phase === "finished")} className="dl-btn dl-btn--plain" onClick={embedded ? () => void endConversation() : leave}>
                {embedded ? <T>End conversation</T> : <T>Leave</T>}
              </button>
            </div>
          </aside>
        ) : null}
      </div>
      {phase === "finished" && feedback && (feedback.analysis || feedback.weak_words?.length) ? <section className="dl-card stack" aria-label={t("Session summary")}>
        {feedback.weak_words?.length ? <p><T v1={feedback.weak_words.join(", ")}>{"Words to practise saying: {v1}"}</T></p> : null}
        {feedback.analysis ? <SessionAnalysis analysis={feedback.analysis} /> : null}
      </section> : null}
    </div>
  );
}
