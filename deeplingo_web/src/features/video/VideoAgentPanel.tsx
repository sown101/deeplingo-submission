import { useCallback } from "react";
import type { CompanionPhase } from "../companion/CompanionConversation";
import type { WatchingVideo } from "../companion/RealtimeScreen";
import { AgentConversation } from "../companion/AgentConversation";
import type { PracticeSuggestion } from "../companion/companionModels";

export function VideoAgentPanel({ watching, onPractice, onPhaseChange }: {
  watching: WatchingVideo;
  onPractice: (suggestion: PracticeSuggestion) => void;
  onPhaseChange: (phase: CompanionPhase) => void;
}) {
  const notify = useCallback((next: CompanionPhase) => {
    if (next === "starting" || next === "recording") watching.onTalk();
    onPhaseChange(next);
  }, [onPhaseChange, watching]);
  return <div className="stack video-agent-conversation">
    <AgentConversation entry="video" item={watching.item} watching={watching} onPractice={onPractice} onPhaseChange={notify} />
  </div>;
}
