import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useContainer } from "../../app/container";
import { T, useT } from "../../i18n/i18n";
import { ProfileActionRow } from "../account/ProfileParts";

// Learner-owned data: download everything stored about you and read the privacy notice. The account's own
// rows (such as deleting it) come in as children so they sit in the same list.
export function YourDataCard({ children }: { children?: ReactNode }) {
  const t = useT();
  const { client } = useContainer();
  const [state, setState] = useState<"idle" | "loading" | "failed">("idle");

  async function download() {
    setState("loading");
    try {
      const data = await client.get<unknown>("/learner/me/export", { timeoutMs: 60_000 });
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "deeplingo-my-data.json";
      link.click();
      URL.revokeObjectURL(url);
      setState("idle");
    } catch {
      setState("failed");
    }
  }

  return (
    <section className="pf-card" aria-labelledby="pf-data-title">
      <h2 id="pf-data-title"><T>Data and account</T></h2>
      <div className="pf-rows">
        <ProfileActionRow icon="⬇" title={t("Download my data")}
          subtitle={state === "loading" ? t("Preparing…") : t("A file with everything DeepLingo stores about you")}
          disabled={state === "loading"} onClick={() => void download()} />
        <div className="pf-row">
          <Link className="pf-row__head" to="/privacy">
            <span className="pf-row__icon" aria-hidden="true">🛡</span>
            <span className="pf-row__text"><span><T>Privacy notice</T></span></span>
            <span className="pf-row__chevron" aria-hidden="true">›</span>
          </Link>
        </div>
        {children}
      </div>
      {state === "failed" ? <p className="pf-error" role="alert"><T>The download failed. Please try again.</T></p> : null}
    </section>
  );
}
