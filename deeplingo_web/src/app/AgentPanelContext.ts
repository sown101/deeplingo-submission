import { createContext } from "react";
import type { CompanionPhase } from "../features/companion/CompanionConversation";

// What the persistent Tata launcher offers on a screen with context (the watch page's study part):
// its label and the sentence the conversation opens on.
export interface AgentLauncherContext {
  title: string;
  subtitle: string;
  segmentId: string;
}

// The video keeps its player context; its conversation is displayed in the shared Tata panel.
export const AgentPanelContext = createContext<{
  host: HTMLDivElement | null;
  onPhaseChange: (phase: CompanionPhase) => void;
  onSegmentChange?: (segmentId: string | null) => void;
  onLauncherChange?: (launcher: AgentLauncherContext | null) => void;
} | null>(null);
