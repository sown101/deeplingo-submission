import { expect, test } from "@playwright/test";

for (const width of [390, 700, 1180, 1440]) for (const theme of ["light", "dark"] as const) {
  test(`compact navigation keeps every label, ${width}px ${theme}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ colorScheme: theme });
    await page.addInitScript(() => {
      localStorage.setItem("deeplingo.ui_language", "vi");
      localStorage.setItem("sb-ci-dummy-auth-token", JSON.stringify({ access_token: "nav-dummy.header.token", token_type: "bearer",
        refresh_token: "dummy-refresh", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
        user: { id: "nav-ci-user", aud: "authenticated", role: "authenticated", email: "nav@ci.invalid", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" } }));
    });
    const unexpected: string[] = [];
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      if (url.pathname.startsWith("/api/")) {
        if (route.request().method() === "GET") {
          if (url.pathname.endsWith("/language-profile")) return json({ learning_language: "en", support_language: "vi", is_complete: true });
          if (url.pathname.endsWith("/lists") || url.pathname.endsWith("/word-sets")) return json([]);
        if (url.pathname.endsWith("/review/decks")) return json({ decks: [] });
          // The notebook page counts every saved word for its "All words" set.
          if (url.pathname.endsWith("/words")) return json({ words: [], summary: null });
        }
        unexpected.push(url.pathname); return route.abort();
      }
      return url.origin === "http://localhost:5173" ? route.continue() : route.abort();
    });
    await page.goto("/words/lists");
    const nav = page.getByRole("navigation", { name: "Chính", exact: true });
    await expect(nav).toHaveCount(1);
    for (const label of ["Trang chủ", "Sổ tay"]) {
      const item = nav.getByRole("link", { name: label, exact: true });
      await expect(item.locator(".nav-label")).toBeVisible();
      await expect(item.locator("svg")).toBeVisible();
      const text = await item.locator(".nav-label").boundingBox();
      const link = await item.boundingBox();
      expect(text!.x).toBeGreaterThanOrEqual(link!.x);
      expect(text!.x + text!.width).toBeLessThanOrEqual(link!.x + link!.width + 1);
    }
    if (width >= 700) {
      const bar = await page.locator(".topbar").boundingBox();
      const menu = await page.getByRole("button", { name: "Tài khoản" }).boundingBox();
      const navigation = await nav.boundingBox();
      expect(bar!.width).toBeLessThanOrEqual(960);
      expect(Math.abs(bar!.x + bar!.width / 2 - width / 2)).toBeLessThan(1);
      expect(navigation!.x + navigation!.width).toBeLessThanOrEqual(menu!.x);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(unexpected).toEqual([]);
    await page.screenshot({ path: info.outputPath("navigation-labels.png") });
  });
}
