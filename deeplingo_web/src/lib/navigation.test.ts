import { describe, expect, it } from "vitest";
import { safeInternalLocation } from "./navigation";

describe("safeInternalLocation", () => {
  it("accepts internal application routes", () => {
    expect(safeInternalLocation("/library")).toBe("/library");
    expect(safeInternalLocation("/library/videos/123")).toBe("/library/videos/123");
    expect(safeInternalLocation("/library?x=1#watch")).toBe("/library?x=1#watch");
  });

  it("rejects absolute URLs and scheme-relative open redirects", () => {
    expect(safeInternalLocation("https://evil.example")).toBeNull();
    expect(safeInternalLocation("http://evil.example/x")).toBeNull();
    expect(safeInternalLocation("//evil.example")).toBeNull();
    expect(safeInternalLocation("/\\evil.example")).toBeNull();
    expect(safeInternalLocation("\\/evil.example")).toBeNull();
  });

  it("rejects javascript and data payloads", () => {
    expect(safeInternalLocation("javascript:alert(1)")).toBeNull();
    expect(safeInternalLocation("data:text/html,script")).toBeNull();
  });

  it("rejects non-strings, empty values, and control characters", () => {
    expect(safeInternalLocation(null)).toBeNull();
    expect(safeInternalLocation(undefined)).toBeNull();
    expect(safeInternalLocation(42)).toBeNull();
    expect(safeInternalLocation({ from: "/library" })).toBeNull();
    expect(safeInternalLocation("")).toBeNull();
    expect(safeInternalLocation("/library\r\nSet-Cookie: x")).toBeNull();
  });

  it("rejects absurdly long values", () => {
    expect(safeInternalLocation(`/${"a".repeat(600)}`)).toBeNull();
  });
});
