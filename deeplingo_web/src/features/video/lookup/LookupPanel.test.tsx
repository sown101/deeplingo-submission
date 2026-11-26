import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { TranscriptSegmentView } from "../../../lib/api/dto";
import { useLookupOverlay } from "./LookupPanel";

const first = "9556593f-b7d7-4e10-9de6-39b5f4dc25f7";
const second = "f5c633e3-4d6a-4405-8c9d-374ec0f43dad";

it("opens one learning object when a phrase has several senses on the same span", () => {
  const occurrence = (id: string) => ({ learning_object_id: id, start_codepoint: 60, end_codepoint: 72, grammar_key: null });
  const segment = { segment_id: "s1", text: "x", learning_objects: [occurrence(first), occurrence(second)] } as unknown as TranscriptSegmentView;
  const { result } = renderHook(() => useLookupOverlay({ pause: vi.fn(), onLookedUp: vi.fn() }));
  act(() => result.current.onOccurrenceTap(segment, [first, second]));
  expect(result.current.overlay).toMatchObject({ kind: "concept", learningObjectId: first });
});
