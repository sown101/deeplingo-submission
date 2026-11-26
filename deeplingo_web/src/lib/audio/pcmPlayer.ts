// Gapless playback of streamed 16-bit mono PCM (realtime companion).
//
// Chunks are scheduled back to back on one AudioContext; flush() drops everything still queued, which
// is what the learner expects when they interrupt the companion.

export interface PcmPlayer {
  enqueue(samples: Int16Array, sampleRate: number): void;
  flush(): void;
  close(): void;
}

export function createPcmPlayer(): PcmPlayer {
  const context = new AudioContext();
  let playing: AudioBufferSourceNode[] = [];
  let nextAt = 0;

  return {
    enqueue(samples, sampleRate) {
      if (samples.length === 0 || context.state === "closed") return;
      if (context.state === "suspended") void context.resume().catch(() => {});
      const buffer = context.createBuffer(1, samples.length, sampleRate);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i += 1) channel[i] = samples[i] / 0x8000;
      const node = context.createBufferSource();
      node.buffer = buffer;
      node.connect(context.destination);
      const startAt = Math.max(nextAt, context.currentTime + 0.05);
      node.start(startAt);
      nextAt = startAt + buffer.duration;
      playing.push(node);
      node.onended = () => {
        playing = playing.filter((item) => item !== node);
      };
    },
    flush() {
      for (const node of playing) {
        try {
          node.stop();
        } catch {
          // already stopped
        }
      }
      playing = [];
      nextAt = 0;
    },
    close() {
      this.flush();
      void context.close().catch(() => {});
    },
  };
}
