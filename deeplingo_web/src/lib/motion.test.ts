import { describe, expect, it, vi, afterEach } from "vitest";
import { prefersReducedMotion, resolveScrollBehavior } from "./motion";

function mockMatchMedia(matches: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
}

describe("prefersReducedMotion", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    // restore the jsdom default (matchMedia exists but is a stub)
    mockMatchMedia(false);
  });

  it("returns true when the user prefers reduced motion", () => {
    mockMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
  });

  it("returns false when no reduced-motion preference is set", () => {
    mockMatchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
  });

  it("fails closed to no preference when matchMedia is unavailable", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: undefined,
    });
    expect(prefersReducedMotion()).toBe(false);
  });

  it("fails closed when matchMedia throws", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: vi.fn(() => {
        throw new Error("unavailable");
      }),
    });
    expect(prefersReducedMotion()).toBe(false);
  });
});

describe("resolveScrollBehavior", () => {
  it("uses instant scrolling for reduced motion", () => {
    expect(resolveScrollBehavior(true)).toBe("auto");
  });

  it("keeps smooth scrolling otherwise", () => {
    expect(resolveScrollBehavior(false)).toBe("smooth");
  });
});
