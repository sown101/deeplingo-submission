import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useContainer } from "../../app/container";
import { planItemPath, type PlanItem } from "./planModels";
import { T, useT } from "../../i18n/i18n";

const KIND_LABEL: Record<PlanItem["kind"], string> = {
  review: "Review",
  conversation: "Talk with your companion",
  video_practice: "Practise a video",
  my_words: "My words",
  add_video: "Add a video",
};

/** Next steps the companion added to today's plan when a conversation ended. */
export function FollowUpList({ items }: { items: PlanItem[] }) {
  const t = useT();
  const { plan } = useContainer();
  const navigate = useNavigate();
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const visible = items.filter((item) => !hidden.has(item.id));
  if (visible.length === 0) return null;

  async function start(item: PlanItem) {
    setBusy(true);
    try {
      await plan.accept(item.id);
    } catch {
      // Recording the choice is secondary: the learner goes on either way.
    }
    navigate(planItemPath(item));
  }

  async function later(item: PlanItem) {
    setBusy(true);
    try {
      await plan.dismiss(item.id);
      setHidden((current) => new Set(current).add(item.id));
    } catch {
      // Keep it on screen; the learner can try again.
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card follow-ups" aria-label={t("Next steps")}>
      <h3><T>Suggested next steps</T></h3>
      <ul className="plan-items">
        {visible.map((item) => (
          <li key={item.id} className="plan-item">
            <div className="plan-item-body">
              <strong>{t(KIND_LABEL[item.kind])}</strong>
              {item.video_title ? <span className="muted">{item.video_title}</span> : null}
              <span className="plan-reason" lang="vi">{item.reason}</span>
            </div>
            <div className="plan-item-actions">
              <button type="button" className="dl-btn dl-btn--primary dl-btn--sm" disabled={busy} onClick={() => void start(item)}>
                <T>Start</T>
              </button>
              <button type="button" className="dl-btn dl-btn--plain dl-btn--sm" disabled={busy}
                aria-label={`${t("Not today")}: ${t(KIND_LABEL[item.kind])}`} onClick={() => void later(item)}>
                <T>Not today</T>
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
