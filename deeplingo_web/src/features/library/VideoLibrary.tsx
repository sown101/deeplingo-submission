import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContainer } from "../../app/container";
import { ApiError } from "../../lib/api/errors";
import type { LibraryVideoSummary } from "../../lib/api/dto";
import { CoverageBadge } from "../coverage/CoverageViews";
import type { CoverageSummary } from "../coverage/coverageModels";
import { T, useT, tr } from "../../i18n/i18n";

const POLL_INTERVAL_MS = 4_000;

// The learner's videos, shown on Home: one link form and every video, ranked by how well it fits.
export function VideoLibrary() {
  const t = useT();
  const { library, coverage, onboarding } = useContainer();
  // Coverage needs a declared level; without one the server sends no estimate, so say where to set it.
  const profileQuery = useQuery({ queryKey: ["language-profile"], queryFn: () => onboarding.loadProfile(), retry: false });
  const needsLevel = profileQuery.isSuccess && !profileQuery.data.declared_level;
  const queryClient = useQueryClient();
  const [importUrl, setImportUrl] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const libraryQuery = useQuery({
    queryKey: ["library"],
    queryFn: () => library.listVideos(),
  });

  // Memoize the list identity so downstream memos/effects keyed on it do not
  // recompute on every render of the polling loop.
  const videos = useMemo(() => libraryQuery.data ?? [], [libraryQuery.data]);

  // Coverage decorates and orders cards; unavailable estimates preserve the server order.
  const hasReadyVideo = videos.some((video) => video.processing_status === "ready");
  const coverageQuery = useQuery({
    queryKey: ["video-coverage"],
    queryFn: () => coverage.forLibrary(),
    enabled: hasReadyVideo,
    retry: false,
    staleTime: 60_000,
  });
  const coverageById = useMemo(
    () => new Map((coverageQuery.data ?? []).map((item) => [item.libraryItemId, item] as const)),
    [coverageQuery.data],
  );
  const rankedVideos = useMemo(() => {
    const rank = { suitable: 0, challenging: 1, hard: 2 };
    return [...videos].sort((a, b) => {
      const left = coverageById.get(a.library_item_id), right = coverageById.get(b.library_item_id);
      const difference = (left?.label ? rank[left.label] : 3) - (right?.label ? rank[right.label] : 3);
      return difference || (left?.coverage != null && right?.coverage != null
        ? Math.abs(left.coverage - 0.95) - Math.abs(right.coverage - 0.95) : 0);
    });
  }, [videos, coverageById]);
  const activeIds = useMemo(
    () =>
      videos
        .filter((v) => v.processing_status === "pending" || v.processing_status === "processing")
        .map((v) => v.library_item_id),
    [videos],
  );

  // One-shot polling timer: refresh only while an item is pending/processing.
  const pollTimer = useRef<number | null>(null);
  useEffect(() => {
    if (activeIds.length === 0) {
      if (pollTimer.current !== null) {
        window.clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
      return;
    }
    if (pollTimer.current !== null) return;
    pollTimer.current = window.setTimeout(() => {
      pollTimer.current = null;
      libraryQuery.refetch().finally(() => {
        // next timer is scheduled by the effect rerun after data changes
      });
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollTimer.current !== null) {
        window.clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [activeIds.length, libraryQuery]);

  const importMutation = useMutation({
    mutationFn: (url: string) => library.importVideo(url),
    onSuccess: () => {
      setImportUrl("");
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ["library"] });
    },
    onError: (error) => {
      setActionError(importErrorMessage(error));
    },
  });

  const retryMutation = useMutation({
    mutationFn: (libraryItemId: string) => library.retryVideo(libraryItemId),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ["library"] });
    },
    onError: (error) => {
      setActionError(importErrorMessage(error));
    },
  });

  const retryLearningMutation = useMutation({
    mutationFn: (libraryItemId: string) => library.retryLearning(libraryItemId),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ["library"] });
    },
    onError: (error) => {
      setActionError(importErrorMessage(error));
    },
  });

  function refresh() {
    libraryQuery.refetch();
  }

  const validImportUrl = importUrl.trim().length <= 2048 && /^https?:\/\/[^\s]+$/i.test(importUrl.trim());

  return (
    <section className="stack library-screen" aria-labelledby="home-videos-title">
      <h2 id="home-videos-title"><T>Your videos</T></h2>
      {needsLevel ? <p className="small muted"><Link to="/account#learning-preferences"><T>Set your level in Profile to see how much of each video you may know.</T></Link></p> : null}

      <form className="library-import-bar" onSubmit={event => {
        event.preventDefault();
        if (validImportUrl && !importMutation.isPending) {
          setActionError(null);
          importMutation.mutate(importUrl.trim());
        }
      }}>
        <label className="sr-only" htmlFor="library-inline-url"><T>Paste a YouTube link</T></label>
        <input id="library-inline-url" type="url" required maxLength={2048} value={importUrl} disabled={importMutation.isPending}
          placeholder={t("Paste a YouTube link")}
          onChange={event => setImportUrl(event.target.value)} />
        <button className="dl-btn dl-btn--primary" disabled={importMutation.isPending || !validImportUrl}>
          {importMutation.isPending ? <T>Importing…</T> : <T>Add</T>}
        </button>
      </form>

      {actionError ? (
        <div className="banner error" role="alert">
          {actionError}
        </div>
      ) : null}

      {libraryQuery.isLoading ? <p role="status"><T>Loading your videos…</T></p> : null}

      {libraryQuery.isError ? (
        <div className="card error-card" role="alert">
          <p><T>Your videos could not be loaded.</T></p>
          <button type="button" className="dl-btn dl-btn--secondary" onClick={refresh}>
            <T>Retry</T>
          </button>
        </div>
      ) : null}

      {!libraryQuery.isLoading && !libraryQuery.isError && videos.length === 0 ? (
        <p className="muted"><T>Paste a YouTube link to start learning from it.</T></p>
      ) : null}

      <ul className="library-list">
        {rankedVideos.map((video) => (
          <LibraryCard
            key={video.library_item_id}
            video={video}
            coverage={coverageById.get(video.library_item_id) ?? null}
            onRetry={() => retryMutation.mutate(video.library_item_id)}
            onRetryLearning={() => retryLearningMutation.mutate(video.library_item_id)}
            busy={
              retryMutation.isPending && retryMutation.variables === video.library_item_id
            }
          />
        ))}
      </ul>

    </section>
  );
}

function LibraryCard({
  video,
  coverage,
  onRetry,
  onRetryLearning,
  busy,
}: {
  video: LibraryVideoSummary;
  coverage: CoverageSummary | null;
  onRetry: () => void;
  onRetryLearning: () => void;
  busy: boolean;
}) {
  const t = useT();
  const ready = video.processing_status === "ready";
  const learningFailed = video.learning_status === "failed";
  const retryable = video.failure?.retryable === true;
  return (
    // A ready card opens the video wherever it is pressed: the title link covers the whole card.
    <li className={`card library-card${ready ? " is-ready" : ""}`}>
      <div className="library-thumb">
        {video.thumbnail_url ? (
          <img src={video.thumbnail_url} alt="" loading="lazy" />
        ) : (
          <div className="thumb-fallback" aria-hidden="true" />
        )}
        <span className="library-lang">{t(LANGUAGE_NAMES[video.language_code] ?? video.language_code)}</span>
        {video.duration_ms !== null && video.duration_ms > 0 ? <span className="library-dur">{formatDuration(video.duration_ms)}</span> : null}
      </div>
      <div className="library-body">
        <h3>{ready ? <Link to={`/library/videos/${video.library_item_id}/watch`}>{video.title}</Link> : video.title}</h3>
        {ready && coverage?.label && coverage.coverage !== null ? (
          <div className={`library-coverage coverage-${coverage.label}`}>
            <CoverageBadge label={coverage.label} coverage={coverage.coverage} languageCode={coverage.languageCode} />
            <span className="library-coverage__bar" aria-hidden="true"><i style={{ width: `${Math.round(coverage.coverage * 100)}%` }} /></span>
          </div>
        ) : null}
        <div className="library-foot">
          <StatusLine video={video} />
          {ready && video.learning_status === "ready"
            ? <span>{t(video.learning_object_count === 1 ? "{n} learning item" : "{n} learning items", { n: video.learning_object_count })}</span>
            : null}
        </div>
      </div>
      <div className="library-actions">
        {video.processing_status === "failed" && retryable ? (
          <button type="button" className="dl-btn dl-btn--secondary" onClick={onRetry} disabled={busy}>
            {busy ? <T>Retrying…</T> : <T>Retry</T>}
          </button>
        ) : null}
        {ready && learningFailed ? (
          <button type="button" className="dl-btn dl-btn--secondary" onClick={onRetryLearning} disabled={busy}>
            {busy ? <T>Retrying…</T> : <T>Retry preparation</T>}
          </button>
        ) : null}
      </div>
    </li>
  );
}

const LANGUAGE_NAMES: Record<string, string> = { en: "English", zh: "Chinese", vi: "Vietnamese" };

function StatusLine({ video }: { video: LibraryVideoSummary }) {
  switch (video.processing_status) {
    case "pending":
      return (
        <p className="status pending" role="status">
          <T>Pending — waiting to be processed</T>
        </p>
      );
    case "processing":
      return (
        <p className="status processing" role="status">
          <T>Processing…</T>
        </p>
      );
    case "ready":
      switch (video.learning_status) {
        case "ready":
          return <p className="status ready"><T>Ready for practice</T></p>;
        case "processing":
          return (
            <p className="status processing" role="status">
              <T>Preparing learning material…</T>
            </p>
          );
        case "not_started":
          return <p className="status"><T>Ready to watch</T></p>;
        case "no_content":
          return <p className="status muted"><T>No practice material available</T></p>;
        case "failed":
          return <p className="status failed"><T>Practice preparation failed</T></p>;
        default:
          return null;
      }
    case "failed":
      return (
        <p className="status failed" role="alert">
          <T>{failureCopy(video.failure?.code) ?? "Processing failed"}</T>
          {video.failure?.retryable ? <T>— you can retry.</T> : <T>— this video cannot be retried.</T>}
        </p>
      );
    default:
      return null;
  }
}

function failureCopy(code: string | undefined): string | null {
  switch (code) {
    case "invalid_video_url":
      return "The video link was not valid";
    case "video_unavailable":
      return "The video is unavailable";
    case "transcript_unavailable":
      return "No transcript was available for this video";
    case "unsupported_content":
      return "This content is not supported yet";
    case "processing_failed":
      return "Processing failed unexpectedly";
    default:
      return null;
  }
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null || durationMs <= 0) return "Unknown length";
  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function importErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail.code === "invalid_video_url") {
      return tr("That link is not a valid YouTube URL.");
    }
    // O12: importing a video that still needs AI work spends a per-learner budget.
    if (error.detail.code === "new_video_budget_exhausted") {
      return tr("You have reached the limit for importing new videos for now. Videos that are already prepared do not count. Please try again later.");
    }
    if (error.detail.code === "import_rate_limited") {
      return tr("Too many import requests. Please wait a moment and try again.");
    }
    if (error.kind === "network" || error.kind === "timeout") {
      return tr("We could not reach the server. Please try again.");
    }
    if (error.kind === "server") {
      return tr("The service is temporarily unavailable. Please try again.");
    }
    return tr("The video could not be imported. Please check the link and try again.");
  }
  return tr("The video could not be imported. Please try again.");
}
