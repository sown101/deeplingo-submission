// Trusted YouTube embed/message boundary.
//
// Watch and dictation embed only backend-validated video IDs through the
// youtube-nocookie.com embed origin. The player posts lifecycle/position
// messages back to the page; the page must apply them only from the trusted
// embed origin and only from the trusted iframe, and must address commands
// only to that origin (never a wildcard target).

export const YOUTUBE_EMBED_ORIGIN = "https://www.youtube-nocookie.com";

export function youTubeEmbedSrc(externalVideoId: string, pageOrigin: string): string {
  return `${YOUTUBE_EMBED_ORIGIN}/embed/${externalVideoId}?enablejsapi=1&origin=${pageOrigin}&playsinline=1`;
}

export function isTrustedPlayerMessage(
  event: MessageEvent,
  expectedSource: Window | null,
): boolean {
  if (event.origin !== YOUTUBE_EMBED_ORIGIN) return false;
  if (expectedSource === null || event.source !== expectedSource) return false;
  return true;
}

export interface PlayerMessage {
  event: string;
  info: unknown;
}

// The embed posts JSON strings; only trusted messages from the expected frame are read.
export function readPlayerMessage(event: MessageEvent, expectedSource: Window | null): PlayerMessage | null {
  if (!isTrustedPlayerMessage(event, expectedSource)) return null;
  let data: unknown = event.data;
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (typeof data !== "object" || data === null) return null;
  const message = data as { event?: unknown; info?: unknown };
  return typeof message.event === "string" ? { event: message.event, info: message.info } : null;
}

// Current position from an `infoDelivery` message, in milliseconds.
export function playerPositionMs(message: PlayerMessage): number | null {
  if (message.event !== "infoDelivery" || typeof message.info !== "object" || message.info === null) return null;
  const time = (message.info as { currentTime?: unknown }).currentTime;
  return typeof time === "number" && Number.isFinite(time) && time >= 0 ? Math.round(time * 1000) : null;
}

// The YouTube player state in a message (-1 unstarted, 0 ended, 1 playing, 2 paused, 3 buffering, 5 cued).
export function playerState(message: PlayerMessage): number | null {
  if (message.event === "onStateChange" && typeof message.info === "number") return message.info;
  if (message.event === "infoDelivery" && typeof message.info === "object" && message.info !== null) {
    const state = (message.info as { playerState?: unknown }).playerState;
    if (typeof state === "number") return state;
  }
  return null;
}

// Playing and buffering both count as playing for the UI.
export function playerIsPlaying(message: PlayerMessage): boolean | null {
  const state = playerState(message);
  return state === null ? null : state === 1 || state === 3;
}

// Ask the embed to stream state/position events back (YouTube widget protocol).
export function postPlayerListening(frame: HTMLIFrameElement | null): void {
  try {
    frame?.contentWindow?.postMessage(
      JSON.stringify({ event: "listening", id: 1, channel: "widget" }),
      YOUTUBE_EMBED_ORIGIN,
    );
  } catch {
    // a not-yet-ready frame is non-fatal
  }
}

export function postPlayerCommand(
  frame: HTMLIFrameElement | null,
  command: { func: string; args?: unknown[] },
): void {
  try {
    frame?.contentWindow?.postMessage(
      JSON.stringify({ event: "command", func: command.func, args: command.args ?? [] }),
      YOUTUBE_EMBED_ORIGIN,
    );
  } catch {
    // posting to a not-yet-ready or cross-origin frame is non-fatal
  }
}
