import { describe, expect, it, vi } from "vitest";
import {
  YOUTUBE_EMBED_ORIGIN,
  isTrustedPlayerMessage,
  playerIsPlaying,
  playerPositionMs,
  readPlayerMessage,
  postPlayerCommand,
  youTubeEmbedSrc,
} from "./media";

function messageEvent(origin: string, source: Window | null): MessageEvent {
  return { origin, source, data: { event: "infoDelivery" } } as unknown as MessageEvent;
}

describe("youTubeEmbedSrc", () => {
  it("builds the trusted nocookie embed URL with the page origin", () => {
    expect(youTubeEmbedSrc("jNQXAC9IVRw", "http://localhost:5173")).toBe(
      "https://www.youtube-nocookie.com/embed/jNQXAC9IVRw?enablejsapi=1&origin=http://localhost:5173&playsinline=1",
    );
  });
});

describe("isTrustedPlayerMessage", () => {
  const trustedSource = {} as Window;

  it("accepts messages from the embed origin and the trusted iframe", () => {
    expect(isTrustedPlayerMessage(messageEvent(YOUTUBE_EMBED_ORIGIN, trustedSource), trustedSource)).toBe(true);
  });

  it("rejects foreign origins (arbitrary windows cannot drive the transcript)", () => {
    expect(isTrustedPlayerMessage(messageEvent("https://evil.example", trustedSource), trustedSource)).toBe(false);
  });

  it("rejects trusted-origin messages from an unexpected frame", () => {
    expect(isTrustedPlayerMessage(messageEvent(YOUTUBE_EMBED_ORIGIN, {} as Window), trustedSource)).toBe(false);
  });

  it("rejects messages when no trusted iframe is mounted", () => {
    expect(isTrustedPlayerMessage(messageEvent(YOUTUBE_EMBED_ORIGIN, trustedSource), null)).toBe(false);
  });
});

describe("postPlayerCommand", () => {
  it("addresses commands only to the trusted embed origin (never a wildcard target)", () => {
    const postMessage = vi.fn();
    const frame = { contentWindow: { postMessage } } as unknown as HTMLIFrameElement;
    postPlayerCommand(frame, { func: "seekTo", args: [1.5, true] });
    expect(postMessage).toHaveBeenCalledWith(
      JSON.stringify({ event: "command", func: "seekTo", args: [1.5, true] }),
      YOUTUBE_EMBED_ORIGIN,
    );
  });

  it("does nothing without a mounted frame", () => {
    expect(() => postPlayerCommand(null, { func: "pauseVideo" })).not.toThrow();
  });

  it("swallows posting failures", () => {
    const frame = {
      contentWindow: {
        postMessage: vi.fn(() => {
          throw new Error("not ready");
        }),
      },
    } as unknown as HTMLIFrameElement;
    expect(() => postPlayerCommand(frame, { func: "pauseVideo" })).not.toThrow();
  });
});

describe("readPlayerMessage", () => {
  const frame = {} as Window;
  const event = (data: unknown, origin = YOUTUBE_EMBED_ORIGIN, source: Window | null = frame) =>
    ({ origin, source, data }) as unknown as MessageEvent;

  it("parses the JSON strings the embed actually posts", () => {
    const message = readPlayerMessage(event(JSON.stringify({ event: "infoDelivery", info: { currentTime: 12.34 } })), frame);
    expect(message).not.toBeNull();
    expect(playerPositionMs(message!)).toBe(12340);
  });

  it("ignores untrusted, malformed or eventless messages", () => {
    expect(readPlayerMessage(event('{"event":"infoDelivery"}', "https://evil.example"), frame)).toBeNull();
    expect(readPlayerMessage(event("not json"), frame)).toBeNull();
    expect(readPlayerMessage(event({ info: 1 }), frame)).toBeNull();
  });

  it("reads playing state from state changes and info deliveries", () => {
    expect(playerIsPlaying({ event: "onStateChange", info: 1 })).toBe(true);
    expect(playerIsPlaying({ event: "onStateChange", info: 2 })).toBe(false);
    expect(playerIsPlaying({ event: "infoDelivery", info: { playerState: 3 } })).toBe(true);
    expect(playerIsPlaying({ event: "infoDelivery", info: { currentTime: 1 } })).toBeNull();
    expect(playerPositionMs({ event: "infoDelivery", info: { currentTime: -1 } })).toBeNull();
  });
});
