import { expect, test, type Page, type Route } from "@playwright/test";

const API = "/api/v1/v3";
const JWT = "presentation-dummy-jwt.header.token";

function json(route: Route, body: unknown): Promise<void> {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

async function setup(page: Page) {
  const session = {
    access_token: JWT, token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "presentation-dummy-refresh",
    user: { id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", aud: "authenticated", role: "authenticated", email: "presentation@ci.invalid",
      app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" },
  };
  await page.addInitScript(([key, value]) => window.localStorage.setItem(key, value as string), [
    "sb-ci-dummy-auth-token", JSON.stringify(session),
  ]);
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith(`${API}/`)) {
      if (url.pathname === `${API}/learner/me/language-profile`) {
        return json(route, { learning_language: "en", support_language: "vi", is_complete: true });
      }
      if (url.pathname === `${API}/learner/me/review/en/due`) {
        return json(route, { language_code: "en", due_count: 2, new_count: 0, cards: ["reservation", "itinerary"].map((text, index) => ({
          concept_id: `c000000${index}-0000-4000-8000-000000000000`, text, reading: null, is_new: false, due_at: "2026-11-01T00:00:00Z",
          exercise: { type: "order", prompt: { kind: "sentence", meaning: "an arrangement to keep a place",
            parts: ["harbour.", "old", "the", "near", "hotel", "small", "a", "at", "nights", "two", "for", "reservation"] } },
        })) });
      }
      return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "fixture route not found" }) });
    }
    if (url.origin === "http://localhost:5173") return route.continue();
    return route.abort();
  });
}

for (const width of [320, 390, 768, 1440]) {
  test(`A review session remains readable without horizontal overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await setup(page);
    await page.goto("/review/en?types=order&images=0");
    await expect(page.locator(".st-progress")).toContainText("1/2");
    await expect(page.getByText("Put the sentence in order")).toBeVisible();
    await expect(page.getByTestId("order-bank").getByRole("button")).toHaveCount(12);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  });
}
