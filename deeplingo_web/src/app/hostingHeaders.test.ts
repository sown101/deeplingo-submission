import { describe, expect, it } from "vitest";
import firebase from "../../firebase.json";

// SEC-06: no other origin may frame the app (clickjacking on signed-in pages).
describe("Firebase Hosting headers", () => {
  const allRoutes = firebase.hosting.headers.find((rule) => rule.source === "**");
  const header = (key: string) => allRoutes?.headers.find((entry) => entry.key === key)?.value;

  it("forbids framing on every route", () => {
    expect(header("Content-Security-Policy")).toContain("frame-ancestors 'none'");
    expect(header("X-Frame-Options")).toBe("DENY");
  });

  it("disables MIME sniffing", () => {
    expect(header("X-Content-Type-Options")).toBe("nosniff");
  });
});
