import { describe, expect, it } from "vitest";
import { ApiError } from "../../lib/api/errors";
import { localDay, parsePlanItem, planItemPath } from "./planModels";

const ITEM = "11111111-1111-1111-1111-111111111111";
const id = (n: number) => `00000000-0000-0000-0000-00000000000${n}`;

// Mirrors backend StudyPlanItemView; companion follow-ups carry the same items.
const rawItems = [
  { id: id(1), kind: "review", status: "open", minutes: 2, reason: "Ôn 4 mục để nhớ lâu hơn.", item_count: 4,
    library_item_id: null, video_title: null, companion_entry: null },
  { id: id(2), kind: "conversation", status: "open", minutes: 5, reason: "Nói về video nhé.", item_count: null,
    library_item_id: ITEM, video_title: "Neil's difficult summer job", companion_entry: "video" },
  { id: id(3), kind: "video_practice", status: "open", minutes: 5, reason: "Làm bài ngắn nhé.", item_count: null,
    library_item_id: ITEM, video_title: "Neil's difficult summer job", companion_entry: null },
];

describe("plan item parsing", () => {
  it("accepts the backend shape and maps items to existing screens", () => {
    const items = rawItems.map(parsePlanItem);
    expect(items.map(planItemPath)).toEqual([
      "/review/quick", `/agent?mode=voice&entry=video&item=${ITEM}`, `/library/videos/${ITEM}/watch`,
    ]);
    expect(planItemPath({ ...items[0], kind: "my_words" })).toBe("/words");
    expect(planItemPath({ ...items[0], kind: "add_video" })).toBe("/home");
  });

  it("rejects unknown or inconsistent proposals", () => {
    const item = rawItems[1];
    for (const broken of [
      { ...item, kind: "grade" },
      { ...item, status: "done" },
      { ...item, companion_entry: null },
      { ...item, library_item_id: null },
      { ...item, library_item_id: "../../admin" },
      { ...rawItems[0], library_item_id: ITEM },
      { ...item, minutes: 0 },
      { ...item, reason: " " },
    ]) {
      expect(() => parsePlanItem(broken)).toThrow(ApiError);
    }
  });

  it("names the plan by the learner's local date", () => {
    expect(localDay(new Date(2026, 0, 5, 23, 30))).toBe("2026-01-05");
  });
});
