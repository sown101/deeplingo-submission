import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { I18nProvider, T, UI_LANGUAGE_KEY, fill, useT } from "./i18n";
import { VI } from "./vi";

function placeholders(text: string): string[] {
  return (text.match(/\{\w+\}/g) ?? []).sort();
}

function Probe() {
  const t = useT();
  return <p aria-label={t("Suggestions for today")}><T>Start</T> <T n={3}>{"{n}-day streak"}</T></p>;
}

describe("interface language (FR-6.1)", () => {
  afterEach(() => window.localStorage.clear());

  it("keeps the placeholders of every Vietnamese entry equal to its English key", () => {
    for (const [english, vietnamese] of Object.entries(VI)) {
      expect(placeholders(vietnamese), english).toEqual(placeholders(english));
    }
  });

  it("fills placeholders and leaves unknown names alone", () => {
    expect(fill("{a} and {b}", { a: 1 })).toBe("1 and {b}");
  });

  it("shows Vietnamese for a Vietnamese support language once the catalog has loaded", async () => {
    render(<I18nProvider language="vi"><Probe /></I18nProvider>);
    expect(await screen.findByText("Bắt đầu Chuỗi 3 ngày")).toBeTruthy();
    expect(screen.getByLabelText("Gợi ý cho hôm nay")).toBeTruthy();
  });

  it("sets the page language on the root element to the interface language", () => {
    const view = render(<I18nProvider language="vi"><Probe /></I18nProvider>);
    expect(document.documentElement.lang).toBe("vi");
    view.rerender(<I18nProvider language="en"><Probe /></I18nProvider>);
    expect(document.documentElement.lang).toBe("en");
  });

  it("shows English for any other support language", () => {
    render(<I18nProvider language="en"><Probe /></I18nProvider>);
    expect(screen.getByText("Start 3-day streak")).toBeTruthy();
  });

  it("lets a stored choice pin English over a Vietnamese support language", () => {
    window.localStorage.setItem(UI_LANGUAGE_KEY, "en");
    render(<I18nProvider language="vi"><Probe /></I18nProvider>);
    expect(screen.getByText("Start 3-day streak")).toBeTruthy();
  });

  it("falls back to the English text when a Vietnamese entry is missing", async () => {
    render(<I18nProvider language="vi"><T>Text with no Vietnamese entry</T></I18nProvider>);
    expect(await screen.findByText("Text with no Vietnamese entry")).toBeTruthy();
  });
});
