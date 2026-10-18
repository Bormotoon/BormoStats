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
    if (path.endsWith("/auth/login")) {
      const body = request.postDataJSON();
      if (body.email === "ann@example.com" && body.password === "correct horse") return json(route, 200, { token: USER_KEY });
      return json(route, 401, { detail: "wrong", error: { code: "unauthorized", message: "wrong", details: [] } });
    }
    if (!key) {
      return json(route, 401, { detail: "missing api key", error: { code: "unauthorized", message: "missing api key", details: [] } });
    }
    if (path.endsWith("/auth/logout")) return json(route, 200, { ok: true });
    if (path.endsWith("/users/me")) return json(route, 200, principal);
    // platform-only endpoints answer a valid non-platform key with 403 (a 401 would sign out)
    if (path.includes("/admin/")) {
      return json(route, 403, { detail: "platform admin only", error: { code: "forbidden", message: "platform admin only", details: [] } });
    }
    if (path.endsWith("/accounts")) return json(route, 200, [{ account_id: "default", marketplace: "wb", organization_id: "acme", title: "Main" }]);
    if (path.includes("/insights/")) return json(route, 200, []);
    return json(route, 200, { items: [], pagination: { limit: 1000, offset: 0, returned: 0, next_offset: null, has_more: false } });
  });
}

async function signInWithKey(page) {
  await page.goto("#/dashboard");
  await page.evaluate((key) => sessionStorage.setItem("bormostats_api_key", key), USER_KEY);
  await page.reload();
}

async function openSettings(page) {
  await page.getByRole("button", { name: /Настройки|Settings/ }).click();
}

test("without a session the sign-in form is shown and no data is requested", async ({ page }) => {
  const seenKeys = [];
  await mockApi(page, { seenKeys });
  await page.goto("#/dashboard");
  await expect(page.getByRole("button", { name: /Войти|Sign in/ })).toBeVisible();
  expect(seenKeys.filter((s) => s.url.includes("/sales/"))).toEqual([]);
});

test("a wrong password is refused and keeps the form", async ({ page }) => {
  await mockApi(page);
  await page.goto("#/dashboard");
  await page.getByLabel(/E-mail/).fill("ann@example.com");
  await page.getByLabel(/Пароль|Password/).fill("nope");
  await page.getByRole("button", { name: /Войти|Sign in/ }).click();
  await expect(page.getByText(/Неверный e-mail или пароль|Wrong e-mail or password/)).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("bormostats_api_key"))).toBeNull();
});

test("signing in sends the session token with every request", async ({ page }) => {
  const seenKeys = [];
  await mockApi(page, { seenKeys });
  await page.goto("#/dashboard");
  await page.getByLabel(/E-mail/).fill("ann@example.com");
  await page.getByLabel(/Пароль|Password/).fill("correct horse");
  await page.getByRole("button", { name: /Войти|Sign in/ }).click();
  await openSettings(page);
  await expect(page.getByText(/Ann Viewer/)).toBeVisible();

  await page.goto("#/sales");
  await expect.poll(() => seenKeys.some((s) => s.url.includes("/sales/daily") && s.key === USER_KEY)).toBe(true);
  // a session is remembered on this device (30 days), and only under its own key
  const stored = await page.evaluate(() => Object.keys(localStorage).filter((k) => localStorage.getItem(k)?.includes("bsk_")));
  expect(stored).toEqual(["bormostats_api_key"]);
});

test("platform-only pages are hidden and show the API's denial", async ({ page }) => {
  await mockApi(page);
  await signInWithKey(page);
  await expect(page.getByRole("link", { name: /Запуски задач|Task runs/ })).toHaveCount(0);
  await page.goto("#/taskRuns");
  await expect(page.getByText(/HTTP 403/)).toBeVisible();
  // a 403 does not sign the user out
  expect(await page.evaluate(() => sessionStorage.getItem("bormostats_api_key"))).toBe(USER_KEY);
});

test("sign out clears the key and returns to the sign-in form", async ({ page }) => {
  await mockApi(page);
  await signInWithKey(page);
  await openSettings(page);
  await page.getByRole("button", { name: /Выйти|Sign out/ }).click();
  await expect(page.getByRole("button", { name: /Войти|Sign in/ })).toBeVisible();
  const left = await page.evaluate(() => [sessionStorage.getItem("bormostats_api_key"), localStorage.getItem("bormostats_api_key")]);
  expect(left).toEqual([null, null]);
});

test("a cross-origin API base is rejected in production builds", async ({ page }) => {
  await mockApi(page);
  await signInWithKey(page);
  await openSettings(page);
  const baseInput = page.getByLabel("API Base URL");
  await baseInput.fill("https://evil.example.com");
  await baseInput.blur();
  await expect(page.getByRole("alert")).toContainText(/VITE_ALLOWED_API_ORIGINS/);
});
