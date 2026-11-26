import { Navigate, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useContainer } from "./container";
import { I18nProvider } from "../i18n/i18n";
import { T } from "../i18n/i18n";

// Language-profile completeness is server authority; a learner who has not
// completed onboarding is routed there before entering the product shell.
export function RequireOnboarding() {
  const { onboarding } = useContainer();
  const profileQuery = useQuery({
    queryKey: ["language-profile"],
    queryFn: () => onboarding.loadProfile(),
    staleTime: Infinity,
    retry: false,
  });

  if (profileQuery.isPending) {
    return (
      <div className="page-center" role="status">
        <p><T>Loading your profile…</T></p>
      </div>
    );
  }
  if (profileQuery.isError) {
    return (
      <div className="page-center">
        <p><T>We could not load your learner profile.</T></p>
        <button type="button" className="dl-btn dl-btn--primary" onClick={() => profileQuery.refetch()}>
          <T>Retry</T>
        </button>
      </div>
    );
  }
  if (!profileQuery.data?.is_complete) {
    return <Navigate to="/onboarding" replace />;
  }
  return (
    <I18nProvider language={profileQuery.data.support_language}>
      <Outlet />
    </I18nProvider>
  );
}
