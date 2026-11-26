import { useCallback, useEffect, useRef, useState } from "react";

// Saves the watch position at most every SAVE_EVERY_MS while it changes, and at once on
// pause, when the tab hides or the page unloads, and when the workspace closes.
//
// Nothing is saved until a successful server read has decided the resume point, so a failed
// read can never overwrite the saved position. When the read succeeds before the learner
// has started watching, the player resumes there. When it succeeds later, the player is not
// moved: the learner is offered the saved point and saving starts once they choose.
export const SAVE_EVERY_MS = 10_000;
const MIN_CHANGE_MS = 1_000;

export type WorkspaceReadStatus = "pending" | "error" | "success";

export function useWatchPosition({
  status,
  savedPositionMs,
  positionMs,
  playing,
  heldPositionMs,
  seek,
  save,
}: {
  /** The workspace read: still loading, failed (possibly retrying), or succeeded. */
  status: WorkspaceReadStatus;
  savedPositionMs: number | null;
  /** The player's own position (not the held one). */
  positionMs: number;
  playing: boolean;
  /** While a practice tool drives the player, the video position to keep (where it returns). */
  heldPositionMs: number | null;
  /** Moves the watched position (the caller decides whether that means the player or a held tool position). */
  seek: (ms: number) => void;
  save: (ms: number, keepalive: boolean) => Promise<unknown>;
}) {
  const [resumedAt, setResumedAt] = useState<number | null>(null);
  const [offeredAt, setOfferedAt] = useState<number | null>(null);
  const decidedRef = useRef(false);
  const lastSavedRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const startedRef = useRef(false);
  const effective = heldPositionMs ?? positionMs;
  const currentRef = useRef(effective);
  currentRef.current = effective;
  const saveRef = useRef(save);
  saveRef.current = save;
  const seekRef = useRef(seek);
  seekRef.current = seek;

  // The learner has started watching once the player played or moved.
  if (playing || positionMs > 0) startedRef.current = true;

  const flush = useCallback((keepalive = false) => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (!decidedRef.current) return;
    const ms = currentRef.current;
    const last = lastSavedRef.current;
    if (last === null ? ms === 0 : Math.abs(ms - last) < MIN_CHANGE_MS) return;
    lastSavedRef.current = ms;
    saveRef.current(ms, keepalive).catch(() => {
      // Not saved: let the next change try again. Position is never learning state.
      if (lastSavedRef.current === ms) lastSavedRef.current = last;
    });
  }, []);

  const decide = useCallback((saved: number | null) => {
    decidedRef.current = true;
    lastSavedRef.current = saved;
    setOfferedAt(null);
  }, []);

  useEffect(() => {
    if (decidedRef.current || offeredAt !== null || status !== "success") return;
    const saved = savedPositionMs !== null && savedPositionMs > 0 ? savedPositionMs : null;
    if (saved === null) {
      decide(savedPositionMs);
    } else if (!startedRef.current) {
      decide(saved);
      seekRef.current(saved);
      setResumedAt(saved);
    } else if (Math.abs(currentRef.current - saved) < MIN_CHANGE_MS) {
      decide(saved);
    } else {
      setOfferedAt(saved);
    }
  }, [status, savedPositionMs, offeredAt, decide]);

  const acceptOffer = useCallback(() => {
    if (offeredAt === null) return;
    decide(offeredAt);
    seekRef.current(offeredAt);
  }, [offeredAt, decide]);

  const declineOffer = useCallback(() => {
    if (offeredAt === null) return;
    decide(offeredAt);
    flush();
  }, [offeredAt, decide, flush]);

  useEffect(() => {
    if (!decidedRef.current || timerRef.current !== null) return;
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      flush();
    }, SAVE_EVERY_MS);
  }, [effective, flush]);

  const wasPlaying = useRef(false);
  useEffect(() => {
    if (wasPlaying.current && !playing) flush();
    wasPlaying.current = playing;
  }, [playing, flush]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush(true);
    };
    const onPageHide = () => flush(true);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onPageHide);
      flush(true);
    };
  }, [flush]);

  return {
    resumedAt,
    clearResumed: () => setResumedAt(null),
    offeredAt,
    acceptOffer,
    declineOffer,
  };
}
