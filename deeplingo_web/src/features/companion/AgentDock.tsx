import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import type { CompanionPhase } from "./CompanionConversation";
import { AgentConversation } from "./AgentConversation";
import { T, useT } from "../../i18n/i18n";
import { Icon } from "../../design/Icon";
import { Mascot } from "../../design/Mascot";
import { agentConversationParams } from "./agentConversationParams";

export function AgentDock({ onClose, onVideoHost, videoPhase, segmentId }: { onClose: () => void; onVideoHost?: (host: HTMLDivElement | null) => void; videoPhase?: CompanionPhase; segmentId?: string | null }) {
  const t = useT();
  const location = useLocation();
  const [topicId, setTopicId] = useState(() => agentConversationParams(location.pathname, location.search).get("topic") ?? "");
  const [conversationPhase, setPhase] = useState<CompanionPhase>("ready");
  const [micBlocked, setMicBlocked] = useState(false);
  const watching = /^\/library\/videos\/[0-9a-f-]{36}\/watch\/?$/i.test(location.pathname);
  const phase = watching ? videoPhase ?? "ready" : conversationPhase;
  const status = micBlocked ? "Microphone unavailable" : phase === "recording" ? "Listening…" : phase === "thinking" ? "Answering…" : phase === "starting" ? "Starting the conversation…" : phase === "finished" ? "Conversation ended" : phase === "failed" ? "Unavailable" : "Ready";
  const item = location.pathname.match(/^\/library\/videos\/([0-9a-f-]{36})(?:\/|$)/i)?.[1] ?? null;
  const entry = item ? "video" : location.pathname.startsWith("/review") ? "review" : "home";
  const params = agentConversationParams(location.pathname, location.search, segmentId, topicId);
  params.delete("mode"); // The full screen already defaults to voice.
  return <aside id="agent-panel" className="agent-panel" role="dialog" aria-label={t("Agent conversation")}>
    <div className="dl-sheet__grip" aria-hidden="true" />
    <header className="ag-head">
      <span className="agent-face" data-state={phase === "recording" ? "listening" : "idle"}><Mascot state={phase === "recording" ? "listen" : phase === "thinking" ? "speak" : "idle"} className="dl-dock-mascot" /></span>
      <div className="ag-heading"><strong>Tata</strong><span className={micBlocked ? "ag-alert-text" : undefined} role={micBlocked ? "alert" : undefined}>
        {micBlocked ? <svg className="ag-alert" viewBox="0 0 24 24" aria-hidden="true"><path fillRule="evenodd" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-1 5h2v7h-2zm0 9h2v2h-2z" /></svg> : null}{t(status)}</span></div>
      <Link to={`/agent?${params}`} className="dl-icon-btn" aria-label={t("Open full conversation")} title={t("Open full conversation")}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>
      </Link>
      <button type="button" className="dl-icon-btn" onClick={onClose} autoFocus aria-label={t("Close agent")} title={t("Close agent")}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </button>
    </header>
    {watching ? <div className="agent-video-host" ref={onVideoHost} /> : <AgentConversation entry={entry} item={item} topicId={topicId} onTopicChange={setTopicId} onLeave={onClose} onPhaseChange={setPhase} onMicError={setMicBlocked} readyActions={<>
      <Link className="dl-chip dl-chip--neutral" to="/review/quick"><Icon name="review" /><T>Review due words</T></Link>
    </>} />}
  </aside>;
}
