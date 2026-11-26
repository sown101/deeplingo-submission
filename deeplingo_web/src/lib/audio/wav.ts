// Pure PCM helpers for speaking practice. The backend accepts only
// 16 kHz, 16-bit, mono PCM WAV, so every browser recording is
// converted here regardless of the microphone's native sample rate.

export const SPEECH_SAMPLE_RATE = 16_000;

/** Streaming box-filter downsampler from the capture rate to 16 kHz. */
export class Downsampler {
  private readonly ratio: number;
  private carry: number[] = [];
  private position = 0;

  constructor(inputRate: number, outputRate = SPEECH_SAMPLE_RATE) {
    if (!(inputRate >= outputRate)) throw new Error("Capture rate must be at least 16 kHz");
    this.ratio = inputRate / outputRate;
  }

  push(input: Float32Array): Int16Array {
    const samples = this.carry.length > 0 ? Float32Array.from([...this.carry, ...input]) : input;
    const output: number[] = [];
    let position = this.position;
    while (position + this.ratio <= samples.length) {
      const start = Math.floor(position);
      const end = Math.floor(position + this.ratio);
      let sum = 0;
      for (let index = start; index < end; index += 1) sum += samples[index];
      output.push(toInt16(sum / Math.max(end - start, 1)));
      position += this.ratio;
    }
    const keepFrom = Math.floor(position);
    this.carry = Array.from(samples.subarray(keepFrom));
    this.position = position - keepFrom;
    return Int16Array.from(output);
  }
}

function toInt16(value: number): number {
  const clamped = Math.max(-1, Math.min(1, value));
  return clamped < 0 ? Math.round(clamped * 0x8000) : Math.round(clamped * 0x7fff);
}

export function concatPcm(parts: Int16Array[]): Int16Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const merged = new Int16Array(total);
  let offset = 0;
  for (const part of parts) {
    merged.set(part, offset);
    offset += part.length;
  }
  return merged;
}

export function pcmDurationMs(samples: Int16Array, rate = SPEECH_SAMPLE_RATE): number {
  return Math.floor((samples.length * 1000) / rate);
}

export function encodeWav(samples: Int16Array, rate = SPEECH_SAMPLE_RATE): Blob {
  return new Blob([encodeWavBytes(samples, rate)], { type: "audio/wav" });
}

export function encodeWavBytes(samples: Int16Array, rate = SPEECH_SAMPLE_RATE): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const ascii = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index));
  };
  ascii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) view.setInt16(44 + index * 2, samples[index], true);
  return buffer;
}

/** Root-mean-square level in 0..1 for a simple microphone meter. */
export function rmsLevel(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.min(1, Math.sqrt(sum / samples.length) * 4);
}
