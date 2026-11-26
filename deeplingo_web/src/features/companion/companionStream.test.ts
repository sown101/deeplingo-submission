import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/api/errors";
import { CompanionApi } from "./companionApi";

// A CompanionTurnView as the backend sends it (the fixture of companion.test.tsx, kept small).
const companionTurn = {
  session_ticket: "signed.ticket.value", expires_at: "2026-10-12T10:00:00Z", turn: 1, max_turns: 20, finished: false,
  language_code: "en", support_language_code: "vi", entry: "home", library_item_id: null, topic: "Travel",
  learner_transcript: "I love flying", reply: "That sounds great. Where did you fly?", reply_support: "Hay quá.",
  hints: { question: null, items: [], frame: null, model_sentence: null }, correction: null, used_items: [],
  next: "continue", audio: { mime_type: "audio/mpeg", base64: "SUQz" }, audio_status: "ready",
};

const streamed = { ...companionTurn, audio: null, audio_status: "streaming" };

function apiWith(lines: unknown[], failure?: unknown) {
  const postFormLines = vi.fn(async (_path: string, _form: FormData, onLine: (line: unknown) => void) => {
    for (const line of lines) onLine(line);
    if (failure) throw failure;
  });
  return { api: new CompanionApi({ postFormLines } as never), postFormLines };
}

describe("streamed text turns", () => {
  it("resolves with the turn as soon as it arrives and hands over each part of its speech in order", async () => {
    const parts: [string, number][] = [];
    const { api, postFormLines } = apiWith([
      { type: "turn", turn: streamed },
      { type: "audio", index: 0, audio: { mime_type: "audio/mpeg", base64: "SUQz" } },
      { type: "audio", index: 1, audio: { mime_type: "audio/mpeg", base64: "not base64!" } },
      { type: "audio", index: 2, audio: { mime_type: "audio/mpeg", base64: "SUQzBA==" } },
      { type: "done" },
    ]);
    const turn = await api.turnText("signed.ticket.value", "I love flying", (audio, index) => parts.push([audio.base64, index]));
    expect(postFormLines.mock.calls[0][0]).toBe("/learner/me/companion/turns/stream");
    expect(turn.reply).toBe(companionTurn.reply);
    expect(turn.audio).toBeNull();
    expect(parts).toEqual([["SUQz", 0], ["SUQzBA==", 2]]); // a malformed part is skipped
  });

  it("rejects like the ordinary turn when the request fails before the turn", async () => {
    const failure = new ApiError("conflict", 409, { code: "companion_session_invalid", message: "Gone" });
    const { api } = apiWith([], failure);
    await expect(api.turnText("t", "hi", vi.fn())).rejects.toBe(failure);
  });

  it("uses the ordinary endpoint when nobody plays the speech", async () => {
    const postForm = vi.fn(async (_path: string) => companionTurn);
    const api = new CompanionApi({ postForm } as never);
    await api.turnText("t", "hi");
    expect(postForm.mock.calls[0][0]).toBe("/learner/me/companion/turns");
  });
});
