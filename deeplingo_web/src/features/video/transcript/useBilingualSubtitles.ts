import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import type { VideoTranscriptView } from "../../../lib/api/dto";

// Bilingual subtitles: when the learner opens a video whose sentences have no meaning in their support language yet,
// the server translates them once (shared by language pair) and the transcript is read again with the meanings.
export function useBilingualSubtitles(libraryItemId: string, transcript: VideoTranscriptView | undefined): boolean {
  const { playback } = useContainer();
  const queryClient = useQueryClient();
  const support = transcript?.translation_language_code ?? null;
  const needed = Boolean(transcript && support && support !== transcript.language_code
    && transcript.segments.some((segment) => !segment.translation));
  const query = useQuery({
    queryKey: ["subtitle-translations", libraryItemId, support],
    queryFn: async () => {
      const added = await playback.ensureTranslations(libraryItemId);
      if (added > 0) await queryClient.invalidateQueries({ queryKey: ["transcript", libraryItemId] });
      return added;
    },
    enabled: needed,
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  return needed && query.isFetching;
}
