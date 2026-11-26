import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { NavLink } from "react-router-dom";
import { useAuth } from "./AuthProvider";
import { RouteContentLoading } from "./RouteSuspense";
import { T, useT } from "../i18n/i18n";
import { Mascot } from "../design/Mascot";
import { PrimaryNavigation } from "./PrimaryNavigation";
import { Icon } from "../design/Icon";
import "./navigation.css";
import { AgentPanelContext, type AgentLauncherContext } from "./AgentPanelContext";
import type { CompanionPhase } from "../features/companion/CompanionConversation";
import { agentConversationParams } from "../features/companion/agentConversationParams";

const AgentDock = lazy(() => import("../features/companion/AgentDock").then(module => ({ default: module.AgentDock })));

export function AppShell() {
  const t = useT();
  const { signOut } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const launcherRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [agentCompact, setAgentCompact] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  const accountButton = useRef<HTMLButtonElement>(null);
  const [agentHost, setAgentHost] = useState<HTMLDivElement | null>(null);
  const [videoPhase, setVideoPhase] = useState<CompanionPhase>("ready");
  const [agentSegmentId, setAgentSegmentId] = useState<string | null>(null);
  const [launcher, setLauncher] = useState<AgentLauncherContext | null>(null);
  const panelContext = useMemo(() => ({
    host: agentHost, onPhaseChange: setVideoPhase, onSegmentChange: setAgentSegmentId, onLauncherChange: setLauncher,
  }), [agentHost]);
  const onAgentPage = location.pathname === "/agent";
  // Study screens stand alone, as in the approved design; the bar would cover their controls.
  const showAgentLauncher = !onAgentPage && !location.pathname.startsWith("/notebook/")
    && !location.pathname.startsWith("/review/");
  // A screen with context (the watch page's study part) names it on the launcher and opens Tata there.
  const agentParams = agentConversationParams(location.pathname, location.search, launcher?.segmentId ?? agentSegmentId);

  function closeAgent() {
    setAgentOpen(false);
    setVideoPhase("ready");
  }

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "l" && !onAgentPage) {
        event.preventDefault();
        if (!event.repeat) {
          setAgentOpen(!agentOpen);
        }
      } else if (event.key === "Escape" && agentOpen) {
        setAgentOpen(false);
      }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [onAgentPage, agentOpen]);

  useEffect(() => {
    window.scrollTo(0, 0);
    setAgentOpen(false);
    setAccountOpen(false);
    setAgentCompact(false);
  }, [location.pathname]);

  useEffect(() => {
    let last = window.scrollY;
    function onScroll() {
      const y = window.scrollY;
      if (Math.abs(y - last) < 12) return;
      setAgentCompact(y > last && y > 80);
      last = y;
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!accountOpen) return;
    function dismiss(event: PointerEvent) {
      if (!accountRef.current?.contains(event.target as Node)) setAccountOpen(false);
    }
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") { setAccountOpen(false); accountButton.current?.focus(); }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        const items = [...(accountRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
        if (!items.length) return;
        event.preventDefault();
        const current = items.indexOf(document.activeElement as HTMLElement);
        items[current < 0 ? event.key === "ArrowDown" ? 0 : items.length - 1 : (current + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
      }
    }
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", keyboard);
    return () => { document.removeEventListener("pointerdown", dismiss); document.removeEventListener("keydown", keyboard); };
  }, [accountOpen]);

  useLayoutEffect(() => {
    if (!agentOpen && wasOpen.current) launcherRef.current?.focus();
    wasOpen.current = agentOpen;
  }, [agentOpen]);

  return (
    <div className={`app-shell dl-app${location.pathname === "/home" || location.pathname === "/progress" ? " home-design" : ""}${onAgentPage ? " agent-page" : ""}${agentOpen && !onAgentPage ? " agent-is-open" : ""}${agentCompact ? " agent-compact" : ""}`}>
      <header className="topbar">
        <NavLink to="/home" className="brand">
          <Mascot className="dl-brand-mascot" />
          DeepLingo
        </NavLink>
        <PrimaryNavigation />
        <div className="account-menu" ref={accountRef}>
          <button ref={accountButton} type="button" className="dl-icon-btn account-trigger" aria-label={t("Account menu")} title={t("Account menu")}
            aria-haspopup="menu" aria-expanded={accountOpen} aria-controls="account-menu" onClick={() => setAccountOpen(value => !value)}><Icon name="profile" /></button>
          {accountOpen ? <nav id="account-menu" role="menu" aria-label={t("Account menu")}>
            <NavLink role="menuitem" to="/account" onClick={() => setAccountOpen(false)}><Icon name="profile" /><T>Profile</T></NavLink>
            <NavLink role="menuitem" to="/account#learning-preferences" onClick={() => setAccountOpen(false)}><Icon name="settings" /><T>Settings</T></NavLink>
            <button type="button" role="menuitem" onClick={() => {
              signOut().then(() => navigate("/signin", { replace: true })).catch(() => {});
            }}><Icon name="logout" /><T>Sign out</T></button>
          </nav> : null}
        </div>
      </header>
      <AgentPanelContext.Provider value={panelContext}><div className="agent-layout">
        <main className="content">
          {/* Lazy screens suspend here, so the shell and nav stay mounted. */}
          <Suspense fallback={<RouteContentLoading />}>
            <Outlet />
          </Suspense>
        </main>
        {agentOpen && !onAgentPage ? <Suspense fallback={<p role="status"><T>Opening agent…</T></p>}>
          <AgentDock key={location.pathname} onClose={closeAgent} onVideoHost={setAgentHost} videoPhase={videoPhase} segmentId={agentSegmentId} />
        </Suspense> : null}
      </div></AgentPanelContext.Provider>
      {showAgentLauncher ? <div className="agent-launcher dl-agent dl-glass" role="group" aria-label="Tata">
        <NavLink to={`/agent?${agentParams}`} className="ag-open" aria-label={launcher?.title ?? t("Talk with Tata")} title={t("Open agent page")}>
          <span className="agent-face"><Mascot className="dl-dock-mascot" /></span>
          <span className="dl-agent__txt">
            <span className="dl-agent__title">{launcher?.title ?? <T>Talk with Tata</T>}</span>
            <span className="dl-agent__sub">{launcher?.subtitle ?? <T>Tap to talk with your agent</T>}</span>
          </span>
        </NavLink>
        <button ref={launcherRef} type="button" className="dl-icon-btn dl-icon-btn--primary" aria-label={t("Open agent")}
          aria-expanded={agentOpen} aria-controls="agent-panel" aria-keyshortcuts="Control+L Meta+L" onClick={() => setAgentOpen(true)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 15 6-6 6 6" /></svg>
        </button>
      </div> : null}
    </div>
  );
}
