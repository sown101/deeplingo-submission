import { createContext, useContext, useMemo, type ReactNode } from "react";
import { ApiClient, type RequestScope } from "../lib/api/apiClient";
import { loadConfig, type AppConfig } from "../lib/config";
import type { AuthGateway } from "../lib/auth/authGateway";
import { useAuth } from "./AuthProvider";
import { LibraryApi } from "../features/library/libraryApi";
import { PlaybackApi } from "../features/video/playbackApi";
import { ProgressApi } from "../features/progress/progressApi";
import { OnboardingApi } from "../features/onboarding/onboardingApi";
import { SpeakingApi } from "../features/speaking/speakingApi";
import { CompanionApi } from "../features/companion/companionApi";
import { WordsApi } from "../features/words/wordsApi";
import { WordListsApi } from "../features/words/listsApi";
import type { NotebookApi } from "../features/words/notebookApi";
import { CoverageApi } from "../features/coverage/coverageApi";
import { PlanApi } from "../features/plan/planApi";
import { ReviewApi } from "../features/review/reviewApi";

export interface AppContainer {
  config: AppConfig;
  gateway: AuthGateway;
  client: ApiClient;
  library: LibraryApi;
  playback: PlaybackApi;
  progress: ProgressApi;
  onboarding: OnboardingApi;
  speaking: SpeakingApi;
  companion: CompanionApi;
  words: WordsApi;
  lists: WordListsApi;
  notebook: NotebookApi;
  coverage: CoverageApi;
  plan: PlanApi;
  review: ReviewApi;
}

// Only the Notebook pages use this API, so its code stays out of the first download.
function lazyNotebook(client: ApiClient): NotebookApi {
  let loaded: Promise<NotebookApi> | null = null;
  const load = () => (loaded ??= import("../features/words/notebookApi").then(module => new module.NotebookApi(client)));
  return new Proxy({} as NotebookApi, {
    get: (_target, method: string) => async (...args: unknown[]) => {
      const api = await load() as unknown as Record<string, (...values: unknown[]) => unknown>;
      return api[method](...args);
    },
  });
}

export function buildContainer(
  config: AppConfig,
  gateway: AuthGateway,
  onUnauthorized?: () => void,
  requestScope?: RequestScope,
): AppContainer {
  const client = new ApiClient({ baseUrl: config.apiBaseUrl, authGateway: gateway, onUnauthorized, requestScope });
  return {
    config,
    gateway,
    client,
    library: new LibraryApi(client),
    playback: new PlaybackApi(client),
    progress: new ProgressApi(client),
    onboarding: new OnboardingApi(client),
    speaking: new SpeakingApi(client),
    companion: new CompanionApi(client),
    words: new WordsApi(client),
    lists: new WordListsApi(client),
    notebook: lazyNotebook(client),
    coverage: new CoverageApi(client),
    plan: new PlanApi(client),
    review: new ReviewApi(client),
  };
}

const ContainerContext = createContext<AppContainer | null>(null);

export function ContainerProvider({
  container,
  children,
}: {
  container: AppContainer;
  children: ReactNode;
}) {
  return <ContainerContext.Provider value={container}>{children}</ContainerContext.Provider>;
}

// useAuth throws outside an AuthProvider, after it has read its context. The hook still runs on every render;
// the error is raised only when no container was provided either.
function useAuthResult() {
  try {
    return { auth: useAuth(), authError: null };
  } catch (error) {
    return { auth: null, authError: error };
  }
}

export function useContainer(): AppContainer {
  const provided = useContext(ContainerContext);
  const { auth, authError } = useAuthResult();
  const signedIn = auth !== null;
  const gateway = auth?.gateway;
  const signOut = auth?.signOut;
  const requestScope = auth?.requestScope;
  // Hooks run in the same order whether or not a container was provided.
  return useMemo(() => {
    if (provided) return provided;
    if (!signedIn) throw authError;
    const config = loadConfig();
    return buildContainer(config, gateway as AuthGateway, () => { void signOut?.().catch(() => {}); }, requestScope);
  }, [provided, signedIn, authError, gateway, signOut, requestScope]);
}
