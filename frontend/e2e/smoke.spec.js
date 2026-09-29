import { expect, test } from "@playwright/test";

const USER_KEY = "bsk_0123456789abcdef_user-secret";

const principal = {
  principal_id: "u-1",
  organization_id: "acme",
  role: "viewer",
  scopes: ["read:analytics"],
  auth_method: "user_key",
  name: "Ann Viewer",
  email: "ann@example.com",
  api_key_expires_at: null,
};

function json(route, status, body) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockApi(page, { seenKeys = [] } = {}) {
  await page.route("**/health/**", (route) => json(route, 200, { status: "ok" }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const key = request.headers()["x-api-key"] || "";
    seenKeys.push({ url: request.url(), key });
    const path = new URL(request.url()).pathname;
    if (!key) {
      return json(route, 401, { detail: "missing api key", error: { code: "unauthorized", message: "missing api key", details: [] } });
    }
    if (path.endsWith("/users/me")) return json(route, 200, principal);
    if (path.includes("/admin/")) {
      return json(route, 401, { detail: "unauthorized", error: { code: "unauthorized", message: "unauthorized", details: [] } });
    }
    if (path.endsWith("/accounts")) return json(route, 200, [{ account_id: "default", marketplace: "wb", organization_id: "acme", title: "Main" }]);
    if (path.includes("/insights/")) return json(route, 200, []);
    return json(route, 200, { items: [], pagination: { limit: 1000, offset: 0, returned: 0, next_offset: null, has_more: false } });
  });
}

async function openSettings(page) {
  await page.getByRole("button", { name: /Настройки|Settings/ }).click();
}

test("without a key the UI explains that data is unavailable", async ({ page }) => {
  await mockApi(page);
  await page.goto("#/dashboard");
  await openSettings(page);
  await expect(page.getByText(/Ключ не задан|No key set/)).toBeVisible();
});

test("entering a user key signs in and sends the key with every request", async ({ page }) => {
  const seenKeys = [];
  await mockApi(page, { seenKeys });
  await page.goto("#/dashboard");
  await openSettings(page);
  const keyInput = page.getByLabel(/API-ключ|API key/);
  await keyInput.fill(USER_KEY);
  await keyInput.press("Enter");
  await expect(page.getByText(/Ann Viewer/)).toBeVisible();

  await page.goto("#/sales");
  await expect.poll(() => seenKeys.some((s) => s.url.includes("/sales/daily") && s.key === USER_KEY)).toBe(true);

  const stored = await page.evaluate(() => ({
    session: sessionStorage.getItem("bormostats_api_key"),
    local: Object.keys(localStorage).filter((k) => localStorage.getItem(k)?.includes("bsk_")),
  }));
  expect(stored.session).toBe(USER_KEY);
  expect(stored.local).toEqual([]);
});

test("admin pages show the denial from the API", async ({ page }) => {
  await mockApi(page);
  await page.goto("#/dashboard");
  await page.evaluate((key) => sessionStorage.setItem("bormostats_api_key", key), USER_KEY);
  await page.goto("#/taskRuns");
  await page.reload();
  await expect(page.getByText(/HTTP 401/)).toBeVisible();
});

test("sign out clears the key", async ({ page }) => {
  await mockApi(page);
  await page.goto("#/dashboard");
  await page.evaluate((key) => sessionStorage.setItem("bormostats_api_key", key), USER_KEY);
  await page.reload();
  await openSettings(page);
  await page.getByRole("button", { name: /Выйти|Sign out/ }).click();
  await expect(page.getByText(/Ключ не задан|No key set/)).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("bormostats_api_key"))).toBeNull();
});

test("a cross-origin API base is rejected in production builds", async ({ page }) => {
  await mockApi(page);
  await page.goto("#/dashboard");
  await openSettings(page);
  const baseInput = page.getByLabel("API Base URL");
  await baseInput.fill("https://evil.example.com");
  await baseInput.blur();
  await expect(page.getByRole("alert")).toContainText(/VITE_ALLOWED_API_ORIGINS/);
});
