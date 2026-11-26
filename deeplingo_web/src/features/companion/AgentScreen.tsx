import { lazy, Suspense, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { RouteContentLoading } from "../../app/RouteSuspense";
import { T, useT } from "../../i18n/i18n";
import { entryFrom } from "./agentConversationParams";
import { AgentStudyRequests } from "./AgentStudyRequests";
import "./agent.css";

const RealtimeScreen = lazy(() => import("./RealtimeScreen").then(module => ({ default: module.RealtimeScreen })));
const CompanionConversation = lazy(() => import("./CompanionConversation").then(module => ({ default: module.CompanionConversation })));

// One agent screen: live voice first; when the microphone or live voice is unavailable, the same conversation
// continues here as typed or recorded turns (the text channel), with the same context.
export function AgentScreen() {
  const t = useT();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [fallback, setFallback] = useState<{ params: string; textOnly: boolean } | null>(null);
  const topicPicker = ["topic", "roleplay"].includes(params.get("practice") ?? "");
  const item = params.get("entry") === "video" ? params.get("item") : null;
  const selected = entryFrom(params);
  const back = item ? `/library/videos/${encodeURIComponent(item)}/watch` : "/home";
  return <section className="agent-screen agent-focus">
    <h1 className="sr-only"><T>Agent</T></h1>
    <header className="agent-focus-top">
      <div className="agent-focus-toolbar">
        <Link className="dl-icon-btn" to={back} aria-label={t("Back home")} title={t("Back home")}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
        </Link>
        <AgentStudyRequests />
      </div>
    </header>
    <Suspense fallback={<RouteContentLoading />}>
      {fallback?.params === params.toString() && selected ? <div className="page companion-screen">
        <CompanionConversation entry={selected.entry} item={selected.item}
          topicId={params.get("topic") ?? undefined}
          segmentId={selected.entry === "video" ? params.get("segment") ?? undefined : undefined}
          scenarioId={params.get("scenario") ?? (topicPicker ? "hotel" : undefined)}
          swapRoles={params.get("swap") === "1"}
          preferText={fallback.textOnly}
          onLeave={() => navigate(back)} />
      </div> : <RealtimeScreen key={params.toString()} fullPage topicPicker={topicPicker}
        onFallback={() => setFallback({ params: params.toString(), textOnly: false })}
        onTextChat={() => setFallback({ params: params.toString(), textOnly: true })} />}
    </Suspense>
  </section>;
}
