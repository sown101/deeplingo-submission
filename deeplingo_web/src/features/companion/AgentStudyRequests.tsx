import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useContainer } from "../../app/container";
import { useT } from "../../i18n/i18n";

export const STUDY_REQUESTS_KEY = "agent-study-requests";

/** What Tata asked the learner to practise again, kept in the agent screen: one quiet button that opens a short
 * list, nothing when the list is empty. Grammar is practised in the notebook's grammar tab and closes on a correct
 * answer; a word closes when it is reviewed; either can be set aside here. Tata also sees the open ones. */
export function AgentStudyRequests() {
  const t = useT();
  const { companion } = useContainer();
  const queryClient = useQueryClient();
  const profile = queryClient.getQueryData<{ learning_language: string; support_language: string | null }>(["language-profile"]);
  const language = profile?.learning_language;
  const support = profile?.support_language ?? "vi";
  const key = [STUDY_REQUESTS_KEY, language, support];
  const query = useQuery({ queryKey: key, queryFn: () => companion.getStudyRequests(language as string, support),
    enabled: Boolean(language), retry: false });
  const dismiss = useMutation({ mutationFn: (id: string) => companion.dismissStudyRequest(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: [STUDY_REQUESTS_KEY] }) });
  const [open, setOpen] = useState(false);
  const items = query.data ?? [];
  if (!items.length) return null;
  return <div className="agent-requests">
    <button type="button" className="dl-chip dl-chip--neutral" aria-expanded={open} aria-controls="agent-requests-list"
      onClick={() => setOpen(value => !value)}>{t("To practise again ({n})", { n: items.length })}</button>
    {open ? <ul id="agent-requests-list" className="agent-requests__list" aria-label={t("To practise again")}>
      {items.map(item => {
        const name = item.title ?? t("No longer available");
        return <li key={item.id}>
          <span className="agent-requests__kind">{t(item.kind === "grammar_redo" ? "Grammar" : "Word")}</span>
          <span className="agent-requests__title">{name}</span>
          {item.kind === "grammar_redo" ? <Link to="/words/lists?tab=grammar">{t("Practise")}</Link> : null}
          <button type="button" className="dl-icon-btn" disabled={dismiss.isPending}
            aria-label={t("Set aside: {name}", { name })} title={t("Set aside: {name}", { name })} onClick={() => dismiss.mutate(item.id)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
          </button>
        </li>;
      })}
    </ul> : null}
    {dismiss.isError ? <p role="alert" className="small">{t("That change could not be saved. Please try again.")}</p> : null}
  </div>;
}
