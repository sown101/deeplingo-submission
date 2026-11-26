import { describe, expect, it } from "vitest";
import { Downsampler, concatPcm, encodeWav, encodeWavBytes, pcmDurationMs, rmsLevel } from "./wav";

describe("speech WAV helpers", () => {
  it("downsamples 48 kHz frames to 16 kHz across frame boundaries", () => {
    const sampler = new Downsampler(48_000);
    const frame = new Float32Array(128).fill(0.5);
    let total = 0;
    for (let index = 0; index < 375; index += 1) total += sampler.push(frame).length; // 1 second
    expect(total).toBeGreaterThanOrEqual(15_999);
    expect(total).toBeLessThanOrEqual(16_000);
  });

  it("supports non-integer ratios such as 44.1 kHz", () => {
    const output = new Downsampler(44_100).push(new Float32Array(44_100).fill(-1));
    expect(Math.abs(output.length - 16_000)).toBeLessThanOrEqual(1);
    expect(output[0]).toBe(-32768);
  });

  it("rejects capture rates below 16 kHz", () => {
    expect(() => new Downsampler(8_000)).toThrow();
  });

  it("encodes canonical 16-bit mono PCM WAV", () => {
    const samples = Int16Array.from([0, 1000, -1000, 32767]);
    const blob = encodeWav(samples);
    const view = new DataView(encodeWavBytes(samples));
    const ascii = (offset: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(offset + i)));
    expect(ascii(0)).toBe("RIFF");
    expect(ascii(8)).toBe("WAVE");
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(8);
    expect(view.getInt16(46, true)).toBe(1000);
    expect(blob.type).toBe("audio/wav");
  });

  it("concatenates chunks and measures duration", () => {
    const merged = concatPcm([new Int16Array(8_000), new Int16Array(8_000)]);
    expect(merged.length).toBe(16_000);
    expect(pcmDurationMs(merged)).toBe(1000);
    expect(rmsLevel(new Float32Array(10))).toBe(0);
    expect(rmsLevel(new Float32Array(10).fill(1))).toBe(1);
  });
});
