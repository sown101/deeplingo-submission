// Motion preference helpers.
//
// The app animates transcript auto-follow with smooth scrolling; users who
// prefer reduced motion must receive instant (non-animated) scrolling.

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function resolveScrollBehavior(reducedMotion: boolean): "smooth" | "auto" {
  return reducedMotion ? "auto" : "smooth";
}
