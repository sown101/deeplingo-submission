import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n/i18n";
import { AppearanceCard } from "../features/account/AppearanceCard";
import { THEME_KEY, applyTheme, saveTheme, storedTheme } from "./theme";

afterEach(() => { window.localStorage.clear(); document.documentElement.removeAttribute("data-theme"); vi.restoreAllMocks(); });

describe("theme choice", () => {
  it("follows the device until the learner picks light or dark, and remembers the pick", () => {
    expect(storedTheme()).toBe("system");
    saveTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(window.localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(storedTheme()).toBe("dark");
    saveTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(window.localStorage.getItem(THEME_KEY)).toBeNull();
  });

  it("ignores an unknown stored value and still works when storage is blocked", () => {
    window.localStorage.setItem(THEME_KEY, "purple");
    expect(storedTheme()).toBe("system");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(storedTheme()).toBe("system");
    expect(() => saveTheme("light")).not.toThrow();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    applyTheme("system");
  });

  it("shows the three choices in Vietnamese and applies the pressed one", async () => {
    render(<I18nProvider language="vi"><AppearanceCard /></I18nProvider>);
    const dark = await screen.findByRole("button", { name: "Tối" });
    expect(screen.getByRole("button", { name: "Theo thiết bị" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(dark);
    expect(dark).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Sáng" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
