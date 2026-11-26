// Microphone capture to 16 kHz PCM for speaking practice.
//
// Audio stays in memory: it is uploaded only for the learner-triggered request
// and is never written to browser storage.

import { Downsampler, concatPcm, rmsLevel } from "./wav";

const WORKLET_SOURCE = `
class DeepLingoCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor("deeplingo-capture", DeepLingoCapture);
`;

export type MicrophoneErrorKind = "unsupported" | "denied" | "unavailable";

export class MicrophoneError extends Error {
  constructor(readonly kind: MicrophoneErrorKind) {
    super(kind);
    this.name = "MicrophoneError";
  }
}

export interface PcmRecorder {
  /** Samples captured since the previous takeChunk() call. */
  takeChunk(): Int16Array;
  /** Stops capture and returns every sample captured since start (empty when started with `streaming`). */
  stop(): Int16Array;
  dispose(): void;
}

export function microphoneSupported(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia &&
    typeof window !== "undefined" && typeof window.AudioContext === "function";
}

/** `streaming`: the caller sends takeChunk() as it goes, so the whole recording is not kept (10 minutes ≈ 19 MB). */
export async function startPcmRecorder(onLevel?: (level: number) => void,
  { streaming = false }: { streaming?: boolean } = {}): Promise<PcmRecorder> {
  if (!microphoneSupported()) throw new MicrophoneError("unsupported");
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (error) {
    const name = error instanceof DOMException ? error.name : "";
    throw new MicrophoneError(name === "NotAllowedError" || name === "SecurityError" ? "denied" : "unavailable");
  }

  const all: Int16Array[] = [];
  let chunk: Int16Array[] = [];
  let active = true;
  let context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let node: AudioNode | null = null;
  let workletUrl: string | null = null;

  const release = () => {
    if (!active) return;
    active = false;
    source?.disconnect();
    node?.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    void context?.close().catch(() => {});
    if (workletUrl) URL.revokeObjectURL(workletUrl);
    onLevel?.(0);
  };

  try {
    const audio = new AudioContext();
    context = audio;
    const downsampler = new Downsampler(audio.sampleRate);
    const accept = (frame: Float32Array) => {
      if (!active) return;
      const samples = downsampler.push(frame);
      if (samples.length > 0) {
        if (!streaming) all.push(samples);
        chunk.push(samples);
      }
      onLevel?.(rmsLevel(frame));
    };
    source = audio.createMediaStreamSource(stream);
    const sink = audio.createGain();
    sink.gain.value = 0;
    sink.connect(audio.destination);
    if (audio.audioWorklet) {
      workletUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "text/javascript" }));
      await audio.audioWorklet.addModule(workletUrl);
      const worklet = new AudioWorkletNode(audio, "deeplingo-capture");
      worklet.port.onmessage = (event: MessageEvent<Float32Array>) => accept(event.data);
      node = worklet;
    } else {
      // Older engines without AudioWorklet.
      const processor = audio.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = (event) => accept(event.inputBuffer.getChannelData(0).slice(0));
      node = processor;
    }
    source.connect(node);
    node.connect(sink);
    if (audio.state === "suspended") await audio.resume();
  } catch {
    // Any setup failure after permission must still release the microphone.
    release();
    throw new MicrophoneError("unavailable");
  }

  return {
    takeChunk() {
      const taken = concatPcm(chunk);
      chunk = [];
      return taken;
    },
    stop() {
      release();
      return concatPcm(all);
    },
    dispose: release,
  };
}
