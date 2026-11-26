import { useCallback, useEffect, useRef, useState } from "react";
import {
  playerIsPlaying,
  playerPositionMs,
  playerState,
  postPlayerCommand,
  postPlayerListening,
  readPlayerMessage,
} from "../../lib/media";
import { clipStep, clipWindow, type ClipWindow } from "./clipTiming";

// The watch page's single YouTube player, shared by the transcript, dictation and
// shadowing modes. Position and state come only from the trusted embed (see lib/media).
// `playClip` plays one sentence (padded, see clipTiming) and pauses at its end; commands sent
// before the player is ready wait for `onReady`.
export function useWatchPlayer() {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [positionMs, setPositionMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const readyRef = useRef(false);
  const queuedRef = useRef<(() => void) | null>(null);
  const clipRef = useRef<{ window: ClipWindow; armed: boolean; onEnd?: () => void } | null>(null);
  const stopTimer = useRef<number | undefined>(undefined);
  const rateRef = useRef(1);

  const send = useCallback((func: string, args: unknown[] = []) => {
    postPlayerCommand(iframeRef.current, { func, args });
  }, []);

  const whenReady = useCallback((action: () => void) => {
    if (readyRef.current) action();
    else queuedRef.current = action;
  }, []);

  const clearStopTimer = useCallback(() => {
    window.clearTimeout(stopTimer.current);
    stopTimer.current = undefined;
  }, []);

  useEffect(() => {
    function endClip() {
      const clip = clipRef.current;
      clipRef.current = null;
      clearStopTimer();
      postPlayerCommand(iframeRef.current, { func: "pauseVideo" });
      setPlaying(false);
      clip?.onEnd?.();
    }
    function onMessage(event: MessageEvent) {
      const message = readPlayerMessage(event, iframeRef.current?.contentWindow ?? null);
      if (!message) return;
      if (message.event === "onReady" || message.event === "initialDelivery") {
        readyRef.current = true;
        const queued = queuedRef.current;
        queuedRef.current = null;
        queued?.();
      }
      const state = playerIsPlaying(message);
      if (state !== null) setPlaying(state);
      // Only a playing player (state 1) moves on; buffering or paused stops the clip clock.
      const rawState = playerState(message);
      if (rawState !== null && rawState !== 1) clearStopTimer();
      const position = playerPositionMs(message);
      if (position !== null) {
        setPositionMs(position);
        const clip = clipRef.current;
        if (clip) {
          const step = clipStep(clip.window, clip.armed, position, rateRef.current);
          clip.armed = step.armed;
          if (step.action.kind === "stop") endClip();
          else if (step.action.kind === "stopIn" && (rawState === null || rawState === 1)) {
            clearStopTimer();
            stopTimer.current = window.setTimeout(endClip, step.action.ms);
          }
        }
      }
      if (message.event === "onStateChange" && message.info === 0) {
        if (clipRef.current) endClip();
        setPositionMs(0);
      }
    }
    window.addEventListener("message", onMessage);
    const frame = iframeRef.current;
    return () => {
      window.removeEventListener("message", onMessage);
      clearStopTimer();
      postPlayerCommand(frame, { func: "pauseVideo" });
    };
  }, [clearStopTimer]);

  const onLoad = useCallback(() => postPlayerListening(iframeRef.current), []);

  const pause = useCallback(() => {
    clipRef.current = null;
    clearStopTimer();
    send("pauseVideo");
  }, [send, clearStopTimer]);

  const play = useCallback(() => {
    clipRef.current = null;
    clearStopTimer();
    send("playVideo");
  }, [send, clearStopTimer]);

  const seek = useCallback((ms: number) => {
    clipRef.current = null;
    clearStopTimer();
    whenReady(() => send("seekTo", [ms / 1000, true]));
    setPositionMs(ms);
  }, [send, whenReady, clearStopTimer]);

  // Segment times in; the clip is padded and stops on its own clock (clipTiming).
  const playClip = useCallback((startMs: number, endMs: number, onEnd?: () => void) => {
    const clip = clipWindow(startMs, endMs);
    clearStopTimer();
    clipRef.current = { window: clip, armed: false, onEnd };
    whenReady(() => {
      send("seekTo", [clip.startMs / 1000, true]);
      send("playVideo");
    });
  }, [send, whenReady, clearStopTimer]);

  const setRate = useCallback((rate: number) => {
    rateRef.current = rate;
    whenReady(() => send("setPlaybackRate", [rate]));
  }, [send, whenReady]);

  return { iframeRef, onLoad, positionMs, setPositionMs, playing, pause, play, seek, playClip, setRate };
}
