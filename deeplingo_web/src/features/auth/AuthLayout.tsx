import type { ReactNode } from "react";
import { T } from "../../i18n/i18n";
import { Link } from "react-router-dom";
import { Mascot } from "../../design/Mascot";

/**
 * Two-panel layout for signed-out and setup screens: a brand panel and the
 * form panel. Stacks to one column on narrow viewports.
 */
export function AuthLayout({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="auth-layout dl-auth">
      <Link className="auth-home" to="/">DeepLingo</Link>
      <div className="auth-panel">
        <div className={wide ? "auth-panel-inner wide" : "auth-panel-inner"}>
          <div className="dl-auth-lockup"><Mascot /><strong>DeepLingo</strong><p><T>Learn from the videos you already love.</T></p></div>
          {children}
        </div>
      </div>
    </div>
  );
}
