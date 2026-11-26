// Clip math for playing one transcript sentence on the YouTube player (Dictation, Shadowing,
// Questions). Sentence times come from the AI transcript at about 0.1 s precision, so the clip is
// widened a little on both sides. The player reports its position only every few hundred ms and
// keeps reporting the old position for a moment after a seek, so the clip:
//  - ignores positions from before the seek (outside the clip window),
//  - stops on a timer computed from the latest position and the playback rate, not on the next report.

export interface ClipPadding {
  leadMs: number;
  tailMs: number;
}

/** Played before the sentence start and after its end. */
export const CLIP_PADDING: ClipPadding = { leadMs: 150, tailMs: 200 };

// A position reported this far before the clip start still counts as "after the seek" (the player
// may land a little early on a keyframe).
const SEEK_LANDING_MS = 1_000;

export interface ClipWindow {
  startMs: number;
  endMs: number;
}

/** The part of the video to play for one sentence. */
export function clipWindow(startMs: number, endMs: number, padding: ClipPadding = CLIP_PADDING): ClipWindow {
  const start = Math.max(0, Math.round(startMs - padding.leadMs));
  const end = Math.max(start + 1, Math.round(endMs + padding.tailMs));
  return { startMs: start, endMs: end };
}

export type ClipAction = { kind: "ignore" } | { kind: "stop" } | { kind: "stopIn"; ms: number };

/**
 * What to do with one reported position while a clip plays. `armed` is false until the first
 * position from after the seek arrives; until then reports are from where the player was before.
 */
export function clipStep(clip: ClipWindow, armed: boolean, positionMs: number, rate: number): { armed: boolean; action: ClipAction } {
  if (!armed) {
    const landed = positionMs >= clip.startMs - SEEK_LANDING_MS && positionMs < clip.endMs;
    if (!landed) return { armed: false, action: { kind: "ignore" } };
  }
  if (positionMs >= clip.endMs) return { armed: true, action: { kind: "stop" } };
  const speed = Number.isFinite(rate) && rate > 0 ? rate : 1;
  return { armed: true, action: { kind: "stopIn", ms: Math.ceil((clip.endMs - positionMs) / speed) } };
}
