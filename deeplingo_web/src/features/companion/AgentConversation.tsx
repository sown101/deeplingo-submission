import { lazy, Suspense, useCallback, useState, type ReactNode } from "react";
import type { CompanionPhase } from "./CompanionConversation";
import type { CompanionEntry, PracticeSuggestion } from "./companionModels";
import type { WatchingVideo } from "./RealtimeScreen";
import type { AgentVoicePhase } from "./AgentVoiceStage";
import { T, useT } from "../../i18n/i18n";

const RealtimeScreen = lazy(() => import("./RealtimeScreen").then(module => ({ default: module.RealtimeScreen })));
const CompanionConversation = lazy(() => import("./CompanionConversation").then(module => ({ default: module.CompanionConversation })));

// One entry for embedded Tata: live first, explicit turn-based fallback after a live error.
export function AgentConversation({ entry, item, watching, onPractice, onLeave, onPhaseChange, onMicError, readyActions, topicId, onTopicChange }: {
  entry: CompanionEntry; item: string | null; watching?: WatchingVideo;
  onPractice?: (suggestion: PracticeSuggestion) => void; onLeave?: () => void;
  onPhaseChange?: (phase: CompanionPhase) => void; onMicError?: (blocked: boolean) => void; readyActions?: ReactNode;
  topicId?: string; onTopicChange?: (topicId: string) => void;
}) {
  const [fallback, setFallback] = useState<"turns" | "text" | null>(null);
  const t = useT();
  const [phase, setPhase] = useState<AgentVoicePhase>("idle");
  const notify = useCallback((next: AgentVoicePhase) => {
    setPhase(next);
    onPhaseChange?.(next === "idle" ? "ready" : next === "connecting" ? "starting"
      : next === "live" ? "recording" : next === "ended" ? "finished" : "failed");
  }, [onPhaseChange]);
  if (fallback) return <Suspense fallback={<p role="status"><T>Loading your conversation…</T></p>}>
    <CompanionConversation embedded entry={entry} item={item} onPractice={onPractice}
      preferText={fallback === "text"} onLeave={onLeave} onPhaseChange={onPhaseChange} watching={watching} topicId={topicId} />
  </Suspense>;
  return <>
    {phase === "idle" ? readyActions : null}
    {phase === "idle" ? <details className="video-agent-tools">
      <summary className="dl-icon-btn" aria-label={t("More conversation tools")} title={t("More conversation tools")}>⋯</summary>
      <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => setFallback("turns")}><T>Use recorded turns</T></button>
    </details> : null}
    <Suspense fallback={<p role="status"><T>Loading your conversation…</T></p>}>
      <RealtimeScreen compact context={{ entry, item, topicId }} watching={watching} onPhaseChange={notify} onMicError={onMicError} onTopicChange={onTopicChange}
        onFallback={() => setFallback("turns")} onTextChat={() => setFallback("text")} />
    </Suspense>
  </>;
}
