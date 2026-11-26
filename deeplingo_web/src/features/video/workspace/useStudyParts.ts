import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useContainer } from "../../../app/container";
import { ApiError } from "../../../lib/api/errors";
import { tr } from "../../../i18n/i18n";
import type { StudyRegionView, VideoWorkspaceView } from "./workspaceModels";
import { partAfter, partAt, type VideoPart } from "./videoParts";
import { partKey } from "./PartsBar";

export function workspaceQueryKey(libraryItemId: string) {
  return ["video-workspace", libraryItemId] as const;
}

function regionErrorMessage(error: unknown): string {
  const code = error instanceof ApiError ? error.detail.code : undefined;
  if (code === "region_invalid") return "That part is too long. Choose up to 40 sentences (about 5 minutes).";
  if (code === "region_unavailable") return "The transcript has changed. Reload the page and choose the part again.";
  return tr("We could not save your part. Please try again.");
}

// The study part: the AI parts of the video, which one is open, and saving a new one on the server.
export function useStudyParts({ libraryItemId, workspaceQuery, parts, region, seek, play, requested = null }: {
  libraryItemId: string;
  workspaceQuery: UseQueryResult<VideoWorkspaceView>;
  parts: VideoPart[] | undefined;
  region: StudyRegionView | null;
  seek: (ms: number) => void;
  play: () => void;
  /** A part named in the link (an agent card): it is saved as the study part and replaces the automatic one. */
  requested?: { start_segment_id: string; end_segment_id: string } | null;
}) {
  const { playback } = useContainer();
  const queryClient = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = useCallback(async (part: { start_segment_id: string; end_segment_id: string }): Promise<boolean> => {
    if (saving) return false;
    setSaving(true);
    setError(null);
    try {
      queryClient.setQueryData<VideoWorkspaceView>(
        workspaceQueryKey(libraryItemId),
        await playback.saveStudyRegion(libraryItemId, part.start_segment_id, part.end_segment_id),
      );
      return true;
    } catch (cause) {
      setError(regionErrorMessage(cause));
      return false;
    } finally {
      setSaving(false);
    }
  }, [saving, playback, queryClient, libraryItemId]);

  // Choosing a part starts it from its first sentence, so there is no separate "play part" button.
  async function changePart(key: string) {
    const part = parts?.find((item) => partKey(item) === key);
    if (part && await save(part)) {
      seek(part.start_ms);
      play();
    }
  }

  async function studyNext(part: VideoPart) {
    if (await save(part)) seek(part.start_ms);
  }

  // Asking again for the same part re-admits a failed, retryable preparation on the server.
  async function retryPreparation() {
    if (region) await save(region);
  }

  // No region yet: open the AI part holding the saved position, once per visit. The learner can move to another part.
  const autoOpened = useRef(false);
  const autoPartKey = useRef<string | null>(null);
  const savedPositionMs = workspaceQuery.data?.position_ms;
  const requestedKey = requested ? `${requested.start_segment_id}_${requested.end_segment_id}` : null;
  const openedRequest = useRef<string | null>(null);
  useEffect(() => {
    if (requested === null || requestedKey === null || !workspaceQuery.isSuccess || openedRequest.current === requestedKey) return;
    openedRequest.current = requestedKey;
    autoOpened.current = true;
    void (async () => {
      const same = region?.start_segment_id === requested.start_segment_id && region.end_segment_id === requested.end_segment_id;
      if (!same && !(await save(requested))) return;
      const opened = queryClient.getQueryData<VideoWorkspaceView>(workspaceQueryKey(libraryItemId))?.region ?? region;
      if (opened) seek(opened.start_ms);
    })();
    // save and seek only read state that is settled when this runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceQuery.isSuccess, requestedKey]);
  useEffect(() => {
    if (requested !== null || autoOpened.current || !workspaceQuery.isSuccess || !parts || region) return;
    autoOpened.current = true;
    const part = partAt(parts, savedPositionMs);
    if (part) {
      autoPartKey.current = partKey(part);
      void save(part);
    }
    // save only reads state that is settled when this runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceQuery.isSuccess, parts, region, savedPositionMs]);

  return {
    saving, error, changePart, studyNext, retryPreparation, autoPartKey,
    currentPart: region && parts
      ? parts.find((part) => part.start_segment_id === region.start_segment_id && part.end_segment_id === region.end_segment_id)
      : undefined,
    nextPart: partAfter(parts ?? [], region),
  };
}
