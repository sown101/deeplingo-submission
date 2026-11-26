import { lazy, useCallback, useMemo } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./app/AuthProvider";
import { RequireAuth } from "./app/RequireAuth";
import { RequireOnboarding } from "./app/RequireOnboarding";
import { RouteSuspense } from "./app/RouteSuspense";
import { ContainerProvider, buildContainer } from "./app/container";
import { loadConfig, isConfigured } from "./lib/config";
import { createSupabaseGateway } from "./lib/auth/authGateway";
import { AuthScreen } from "./features/auth/AuthScreen";
import { ForgotPasswordScreen } from "./features/auth/ForgotPasswordScreen";
import { ResetPasswordScreen } from "./features/auth/ResetPasswordScreen";
import { I18nProvider, T } from "./i18n/i18n";

// Feature screens load on demand per route (see RouteSuspense). Auth stays
// eager: it is the first surface every visitor reaches.
const AppShell = lazy(() =>
  import("./app/AppShell").then((m) => ({ default: m.AppShell })),
);
const OnboardingScreen = lazy(() =>
  import("./features/onboarding/OnboardingScreen").then((m) => ({ default: m.OnboardingScreen })),
);
const HomeScreen = lazy(() =>
  import("./features/home/HomeScreen").then((m) => ({ default: m.HomeScreen })),
);
const WatchScreen = lazy(() =>
  import("./features/video/WatchScreen").then((m) => ({ default: m.WatchScreen })),
);
const ProgressScreen = lazy(() => import("./features/progress/ProgressScreen").then((m) => ({ default: m.ProgressScreen })));
const ReviewScreen = lazy(() =>
  import("./features/notebookStudy/PracticeScreen").then((m) => ({ default: m.PracticeScreen })),
);
const StudyRoute = lazy(() => import("./features/notebookStudy/StudyRoute").then((m) => ({ default: m.StudyRoute })));
const ReviewRedirect = lazy(() => import("./features/review/ReviewDecks").then((m) => ({ default: m.ReviewRedirect })));
const WordListsScreen = lazy(() =>
  import("./features/words/WordListsScreen").then((m) => ({ default: m.WordListsScreen })),
);
const WordListScreen = lazy(() =>
  import("./features/words/WordListScreen").then((m) => ({ default: m.WordListScreen })),
);
const WordSetScreen = lazy(() => import("./features/words/WordSetScreen").then((m) => ({ default: m.WordSetScreen })));
const MyWordsScreen = lazy(() =>
  import("./features/words/MyWordsScreen").then((m) => ({ default: m.MyWordsScreen })),
);
const PrivacyScreen = lazy(() =>
  import("./features/privacy/PrivacyScreen").then((m) => ({ default: m.PrivacyScreen })),
);
const AccountScreen = lazy(() =>
  import("./features/account/AccountScreen").then((m) => ({ default: m.AccountScreen })),
);
const AgentScreen = lazy(() => import("./features/companion/AgentScreen").then(module => ({ default: module.AgentScreen })));
const LandingScreen = lazy(() => import("./features/landing/LandingScreen").then(module => ({ default: module.LandingScreen })));

function ConfigGate({ children }: { children: React.ReactNode }) {
  const config = loadConfig();
  // Production builds enforce the safe API-origin policy (HTTPS, no
  // localhost/dev infrastructure); development stays permissive.
  if (!isConfigured(config, import.meta.env.PROD)) {
    return (
      <div className="page-center">
        <h1><T>Configuration required</T></h1>
        <p>
          <T>This build is missing valid browser configuration. Required variables:</T>{" "}
          <code>VITE_API_BASE_URL</code>, <code>VITE_SUPABASE_URL</code>,{" "}
          <code>VITE_SUPABASE_PUBLISHABLE_KEY</code><T>. In production builds the API origin must use HTTPS (same-origin</T> <code>/api/v1/v3</code> <T>is also supported) and must not point at development infrastructure.</T>
        </p>
      </div>
    );
  }
  return children;
}

export function App() {
  return <Routes>
    <Route path="/" element={<RouteSuspense><LandingScreen /></RouteSuspense>} />
    <Route path="/landing" element={<RouteSuspense><LandingScreen /></RouteSuspense>} />
    <Route path="*" element={<ConfiguredApp />} />
  </Routes>;
}

function ConfiguredApp() {
  const gateway = useMemo(() => createSupabaseGateway(loadConfig()), []);
  return (
    <ConfigGate>
      <AuthProvider gateway={gateway}>
        <AppRoutesWithContainer />
      </AuthProvider>
    </ConfigGate>
  );
}

function AppRoutesWithContainer() {
  const { gateway, signOut, requestScope } = useAuth();
  const onUnauthorized = useCallback(() => { void signOut().catch(() => {}); }, [signOut]);
  const container = useMemo(() => buildContainer(loadConfig(), gateway, onUnauthorized, requestScope), [gateway, onUnauthorized, requestScope]);
  return (
    <ContainerProvider container={container}>
      <RouteSuspense>
        <Routes>
          <Route path="/signin" element={<I18nProvider language="vi"><AuthGate /></I18nProvider>} />
          <Route path="/forgot-password" element={<I18nProvider language="vi"><ForgotPasswordScreen /></I18nProvider>} />
          <Route path="/privacy" element={<I18nProvider language="vi"><PrivacyScreen /></I18nProvider>} />
          <Route path="/reset-password" element={<I18nProvider language="vi"><ResetPasswordScreen /></I18nProvider>} />
          <Route element={<RequireAuth />}>
            {/* Like sign-in, set-up speaks Vietnamese before the learner has chosen a support language. */}
            <Route path="/onboarding" element={<I18nProvider language="vi"><OnboardingGate /></I18nProvider>} />
            <Route element={<RequireOnboarding />}>
              <Route element={<AppShell />}>
                <Route path="/home" element={<HomeScreen />} />
                <Route path="/library/videos/:libraryItemId/watch" element={<WatchScreen />} />
                <Route path="/words" element={<MyWordsScreen />} />
                <Route path="/words/lists" element={<WordListsScreen />} />
                <Route path="/words/lists/:listId" element={<WordListScreen />} />
                <Route path="/words/sets/:setKey" element={<WordSetScreen />} />
                <Route path="/review" element={<ReviewRedirect />} />
                <Route path="/review/quick" element={<ReviewRedirect />} />
                <Route path="/review/:language" element={<ReviewScreen />} />
                <Route path="/notebook/:scope/:mode" element={<StudyRoute />} />
                <Route path="/agent" element={<AgentScreen />} />
                <Route path="/progress" element={<ProgressScreen />} />
                <Route path="/account" element={<AccountScreen />} />
              </Route>
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/signin" replace />} />
        </Routes>
      </RouteSuspense>
    </ContainerProvider>
  );
}

function AuthGate() {
  return (
    <AuthAware>
      {(status) => (status === "authenticated" ? <Navigate to="/onboarding" replace /> : <AuthScreen />)}
    </AuthAware>
  );
}

function AuthAware({ children }: { children: (status: "loading" | "authenticated" | "unauthenticated") => React.ReactNode }) {
  const { status } = useAuth();
  return <>{children(status)}</>;
}

function OnboardingGate() {
  const { status } = useAuth();
  return status === "authenticated" ? <OnboardingScreen /> : <Navigate to="/signin" replace />;
}
