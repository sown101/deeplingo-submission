import { afterEach, describe, expect, it, vi } from "vitest";
import { MicrophoneError, startPcmRecorder } from "./pcmRecorder";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("startPcmRecorder", () => {
  it("releases the microphone when capture setup fails after permission", async () => {
    const stopTrack = vi.fn();
    const close = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) },
    });
    class FailingContext {
      sampleRate = 48_000;
      state = "running";
      destination = {};
      audioWorklet = { addModule: vi.fn().mockRejectedValue(new Error("blocked by CSP")) };
      createMediaStreamSource() { return { connect: vi.fn(), disconnect: vi.fn() }; }
      createGain() { return { gain: { value: 1 }, connect: vi.fn() }; }
      close = close;
    }
    vi.stubGlobal("AudioContext", FailingContext);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:worklet"), revokeObjectURL: vi.fn() }));

    await expect(startPcmRecorder()).rejects.toEqual(new MicrophoneError("unavailable"));
    expect(stopTrack).toHaveBeenCalled();
    expect(close).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:worklet");
  });

  it("does not keep the whole recording when the caller streams chunks", async () => {
    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    });
    const ports: { onmessage: ((event: { data: Float32Array }) => void) | null }[] = [];
    class Context {
      sampleRate = 16_000;
      state = "running";
      destination = {};
      audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
      createMediaStreamSource() { return { connect: vi.fn(), disconnect: vi.fn() }; }
      createGain() { return { gain: { value: 1 }, connect: vi.fn() }; }
      close = vi.fn().mockResolvedValue(undefined);
    }
    class Worklet {
      port = { onmessage: null as ((event: { data: Float32Array }) => void) | null };
      constructor() { ports.push(this.port); }
      connect = vi.fn();
      disconnect = vi.fn();
    }
    vi.stubGlobal("AudioContext", Context);
    vi.stubGlobal("AudioWorkletNode", Worklet);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:worklet"), revokeObjectURL: vi.fn() }));

    const streaming = await startPcmRecorder(undefined, { streaming: true });
    ports[0].onmessage?.({ data: new Float32Array(160).fill(0.5) });
    expect(streaming.takeChunk().length).toBe(160);
    expect(streaming.stop().length).toBe(0);

    const kept = await startPcmRecorder();
    ports[1].onmessage?.({ data: new Float32Array(160).fill(0.5) });
    expect(kept.takeChunk().length).toBe(160);
    expect(kept.stop().length).toBe(160);
  });
});
