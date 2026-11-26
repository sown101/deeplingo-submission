import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { T } from "../../i18n/i18n";
import { STUDY_REQUESTS_KEY } from "./AgentStudyRequests";

/** Practice Tata just asked for again. It joins the "To practise again" list of the agent screen; grammar is done in
 * the notebook's grammar tab. */
export function StudyRequestCard({ request }: { request: { kind: "grammar_redo" | "word_review"; item: string; title: string | null } }) {
  const queryClient = useQueryClient();
  useEffect(() => { void queryClient.invalidateQueries({ queryKey: [STUDY_REQUESTS_KEY] }); }, [queryClient, request.item]);
  return (
    <div className="card stack" role="status">
      <strong><T>Tata will remind you to practise this</T></strong>
      <p className="small">{request.title ?? request.item}</p>
      {request.kind === "grammar_redo"
        ? <Link className="dl-btn dl-btn--secondary dl-btn--sm" to="/words/lists?tab=grammar"><T>Do the grammar exercise</T></Link> : null}
    </div>
  );
}
