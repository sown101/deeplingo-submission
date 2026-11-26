import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useWatchPosition, type WorkspaceReadStatus } from "./useWatchPosition";

interface Props {
  status: WorkspaceReadStatus;
  savedPositionMs: number | null;
  positionMs: number;
  playing: boolean;
}

function setup(initial: Props) {
  const seek = vi.fn();
  const save = vi.fn().mockResolvedValue(undefined);
  const hook = renderHook((props: Props) => useWatchPosition({ ...props, heldPositionMs: null, seek, save }), {
    initialProps: initial,
  });
  let current = initial;
  const update = (next: Partial<Props>) => {
    current = { ...current, ...next };
    hook.rerender(current);
  };
  return { hook, seek, save, update };
}

describe("useWatchPosition", () => {
  it("never saves after a failed read: play, pause, pagehide and unmount", () => {
    const { hook, seek, save, update } = setup({ status: "error", savedPositionMs: null, positionMs: 0, playing: false });
    update({ playing: true, positionMs: 5000 });
    update({ playing: false });
    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });
    hook.unmount();
    expect(save).not.toHaveBeenCalled();
    expect(seek).not.toHaveBeenCalled();
  });

  it("restores the saved point when a retry succeeds before the learner started watching", () => {
    const { hook, seek, save, update } = setup({ status: "error", savedPositionMs: null, positionMs: 0, playing: false });
    update({ status: "success", savedPositionMs: 600_000 });
    expect(seek).toHaveBeenCalledWith(600_000);
    expect(hook.result.current.resumedAt).toBe(600_000);
    expect(hook.result.current.offeredAt).toBeNull();
    update({ positionMs: 600_000, playing: true });
    update({ positionMs: 605_000, playing: false });
    expect(save).toHaveBeenCalledWith(605_000, false);
  });

  it("offers the saved point instead of jumping when the learner already started, and saves only after the choice", () => {
    const { hook, seek, save, update } = setup({ status: "error", savedPositionMs: null, positionMs: 0, playing: false });
    update({ playing: true, positionMs: 5000 });
    update({ status: "success", savedPositionMs: 600_000 });
    expect(seek).not.toHaveBeenCalled();
    expect(hook.result.current.offeredAt).toBe(600_000);
    // Undecided: pausing and hiding the page keep the server's 10:00.
    update({ playing: false, positionMs: 6000 });
    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });
    expect(save).not.toHaveBeenCalled();

    act(() => hook.result.current.acceptOffer());
    expect(seek).toHaveBeenCalledWith(600_000);
    expect(hook.result.current.offeredAt).toBeNull();
    update({ positionMs: 600_000, playing: true });
    update({ positionMs: 612_000, playing: false });
    expect(save.mock.calls).toEqual([[612_000, false]]);
  });

  it("saves the current point once the learner chooses to stay", () => {
    const { hook, seek, save, update } = setup({ status: "error", savedPositionMs: null, positionMs: 0, playing: false });
    update({ playing: true, positionMs: 5000 });
    update({ status: "success", savedPositionMs: 600_000, playing: false });
    act(() => hook.result.current.declineOffer());
    expect(seek).not.toHaveBeenCalled();
    expect(save).toHaveBeenCalledWith(5000, false);
  });

  it("saves as before when the read succeeds with no saved position", () => {
    const { hook, seek, save, update } = setup({ status: "pending", savedPositionMs: null, positionMs: 0, playing: false });
    update({ status: "success" });
    expect(hook.result.current.offeredAt).toBeNull();
    update({ playing: true, positionMs: 5000 });
    update({ playing: false });
    expect(seek).not.toHaveBeenCalled();
    expect(save).toHaveBeenCalledWith(5000, false);
  });
});
