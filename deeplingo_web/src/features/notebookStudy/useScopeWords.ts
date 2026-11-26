import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import type { NotebookScope, StudyWord } from "./studyTypes";

export type ScopeWord = StudyWord;

const EMPTY: ScopeWord[] = [];

/** The words of a notebook id, of "all" (saved words in the learning language), or of a level "level-0".."level-4". */
export function useScopeWords(scope: NotebookScope) {
  const { lists, words, onboarding } = useContainer();
  const queryClient = useQueryClient();
  const queryKey = ["notebook-study", scope];
  const query = useQuery({
    queryKey,
    queryFn: async (): Promise<ScopeWord[]> => {
      const level = /^level-([0-4])$/.exec(scope);
      if (scope !== "all" && !level) {
        const detail = await lists.detail(scope);
        return detail.words.map((word) => ({
          conceptId: word.conceptId, languageCode: detail.languageCode, text: word.text, traditional: word.traditional,
          reading: word.reading, gloss: word.gloss, note: word.note, favorite: word.favorite,
        }));
      }
      const profile = await onboarding.loadProfile();
      const view = await words.list(profile.learning_language ?? undefined);
      const rung = level ? Number(level[1]) : null;
      return view.words
        .filter((word) => word.saved && (rung === null || (rung === 4 ? word.rung >= 4 : word.rung === rung)))
        .map((word) => ({
          conceptId: word.conceptId, languageCode: word.languageCode, text: word.text, traditional: word.traditional,
          reading: word.reading, gloss: word.gloss, note: word.note, favorite: word.favorite,
        }));
    },
  });

  // A saved mark shows at once here and is refetched by the notebook pages when they open again.
  const patch = useCallback((conceptId: string, change: Partial<ScopeWord>) => {
    queryClient.setQueryData<ScopeWord[]>(["notebook-study", scope], (current) =>
      current?.map((word) => (word.conceptId === conceptId ? { ...word, ...change } : word)));
    void queryClient.invalidateQueries({ queryKey: ["my-words"] });
    void queryClient.invalidateQueries({ queryKey: ["word-list"] });
  }, [queryClient, scope]);

  return {
    words: query.data ?? EMPTY,
    isLoading: query.isPending,
    isError: query.isError,
    retry: () => void query.refetch(),
    patch,
  };
}
