import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { T } from "../../i18n/i18n";

export const TRANSCRIPT_CONSENT_KEY = ["transcript-consent"];

// FR-3.11: asked once, after voice is allowed. Default off: nothing is kept until the learner says yes,
// and "Not now" is a decision too, so the question does not come back. Profile can change it later.
export function TranscriptConsentPrompt() {
  const { companion } = useContainer();
  const queryClient = useQueryClient();
  // Changes only through this prompt or Profile (which refresh it), so it is not re-read on every mount.
  const query = useQuery({ queryKey: TRANSCRIPT_CONSENT_KEY, queryFn: () => companion.getTranscriptConsent(), retry: false, staleTime: Infinity });
  const decide = useMutation({
    mutationFn: (granted: boolean) => companion.setTranscriptConsent(granted),
    onSuccess: (value) => queryClient.setQueryData(TRANSCRIPT_CONSENT_KEY, value),
  });
  if (query.data?.status !== "ask") return null;
  return (
    <div className="card stack">
      <p><strong><T>Keep transcripts for calibration and review?</T></strong></p>
      <p className="small muted">
        <T>If you allow it, the text of what you say in voice conversations is kept with the agent's question, per-word pronunciation scores and grammar corrections, so your speaking level can be calibrated, you can review your mistakes and the agent can remember your recent turns in later conversations. No audio is kept. Transcripts are deleted after 12 months; you can view, delete or switch this off any time in Profile.</T>
      </p>
      <div className="row">
        <button type="button" className="dl-btn dl-btn--primary dl-btn--sm" disabled={decide.isPending} onClick={() => decide.mutate(true)}><T>Allow keeping transcripts</T></button>
        <button type="button" className="dl-btn dl-btn--plain dl-btn--sm" disabled={decide.isPending} onClick={() => decide.mutate(false)}><T>Not now</T></button>
      </div>
      {decide.isError ? <p className="error small" role="alert"><T>That could not be saved. Please try again.</T></p> : null}
    </div>
  );
}
