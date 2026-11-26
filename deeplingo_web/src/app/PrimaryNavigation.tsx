import { useLayoutEffect, useRef } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Icon } from "../design/Icon";
import { useT } from "../i18n/i18n";

const ITEMS = [
  { to: "/home", label: "Home", icon: "home" },
  { to: "/words/lists", label: "Notebook", icon: "notebook" },
  { to: "/agent", label: "Tata", icon: "mic" },
  { to: "/progress", label: "Progress", icon: "chart" },
] as const;

export function PrimaryNavigation() {
  const t = useT();
  const location = useLocation();
  const navRef = useRef<HTMLElement>(null);
  // Slides one highlight under the active link; NavLink still decides which link is active.
  useLayoutEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const place = () => {
      const active = nav.querySelector<HTMLElement>("a.active");
      nav.style.setProperty("--pill-x", `${active?.offsetLeft ?? 0}px`);
      nav.style.setProperty("--pill-y", `${active?.offsetTop ?? 0}px`);
      nav.style.setProperty("--pill-w", `${active?.offsetWidth ?? 0}px`);
      nav.style.setProperty("--pill-h", `${active?.offsetHeight ?? 0}px`);
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [location.pathname, t]);
  return <div className="topnav-wrap"><nav className="topnav" aria-label={t("Primary")} ref={navRef}>
    <span className="topnav-pill" aria-hidden="true" />
    {ITEMS.map(item => <NavLink key={item.to} to={item.to} aria-label={t(item.label)} title={t(item.label)}
      className={({ isActive }) => isActive || (item.label === "Notebook" && (location.pathname.startsWith("/words") || location.pathname.startsWith("/review") || location.pathname.startsWith("/notebook"))) ? "active" : ""}>
      <Icon name={item.icon} /><span className="nav-label">{t(item.label)}</span>
    </NavLink>)}
  </nav></div>;
}
