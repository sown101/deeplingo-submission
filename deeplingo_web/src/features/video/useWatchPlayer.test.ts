import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { YOUTUBE_EMBED_ORIGIN } from "../../lib/media";
import { CLIP_PADDING } from "./clipTiming";
import { useWatchPlayer } from "./useWatchPlayer";

function setup() {
  const iframe = document.createElement("iframe");
  document.body.appendChild(iframe);
  const frame = iframe.contentWindow!;
  const posted = vi.spyOn(frame, "postMessage").mockImplementation(() => {});
  const hook = renderHook(() => useWatchPlayer());
  hook.result.current.iframeRef.current = iframe;
  const deliver = (data: unknown) =>
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(data), origin: YOUTUBE_EMBED_ORIGIN, source: frame }));
    });
  const commands = () => posted.mock.calls.map(([message]) => JSON.parse(String(message)) as { func: string; args: unknown[] });
  return { hook, deliver, commands, iframe };
}

describe("useWatchPlayer clips", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("seeks to the padded start and pauses at the padded end on its own clock", () => {
    const { hook, deliver, commands } = setup();
    deliver({ event: "onReady" });
    const onEnd = vi.fn();
    act(() => hook.result.current.playClip(10_000, 12_000, onEnd));
    expect(commands()).toContainEqual({ event: "command", func: "seekTo", args: [(10_000 - CLIP_PADDING.leadMs) / 1000, true] });

    // The player still reports where it paused before the seek: ignored, the clip keeps playing.
    deliver({ event: "infoDelivery", info: { currentTime: 12.3, playerState: 2 } });
    expect(onEnd).not.toHaveBeenCalled();

    deliver({ event: "infoDelivery", info: { currentTime: 10, playerState: 1 } });
    const endMs = 12_000 + CLIP_PADDING.tailMs;
    act(() => vi.advanceTimersByTime(endMs - 10_000 - 1));
    expect(onEnd).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(commands().at(-1)).toMatchObject({ func: "pauseVideo" });
  });

  it("stretches the clip clock at a slower rate and holds it while buffering", () => {
    const { hook, deliver } = setup();
    deliver({ event: "onReady" });
    const onEnd = vi.fn();
    act(() => hook.result.current.setRate(0.5));
    act(() => hook.result.current.playClip(4_000, 5_000, onEnd));
    deliver({ event: "infoDelivery", info: { currentTime: 4.85, playerState: 1 } });
    deliver({ event: "onStateChange", info: 3 });
    act(() => vi.advanceTimersByTime(5_000));
    expect(onEnd).not.toHaveBeenCalled();
    deliver({ event: "infoDelivery", info: { currentTime: 5, playerState: 1 } });
    act(() => vi.advanceTimersByTime(Math.ceil((5_000 + CLIP_PADDING.tailMs - 5_000) / 0.5)));
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("a pause or a seek cancels the clip", () => {
    const { hook, deliver } = setup();
    deliver({ event: "onReady" });
    const onEnd = vi.fn();
    act(() => hook.result.current.playClip(1_000, 2_000, onEnd));
    deliver({ event: "infoDelivery", info: { currentTime: 1, playerState: 1 } });
    act(() => hook.result.current.seek(30_000));
    act(() => vi.advanceTimersByTime(5_000));
    deliver({ event: "infoDelivery", info: { currentTime: 31, playerState: 1 } });
    expect(onEnd).not.toHaveBeenCalled();
  });
});
