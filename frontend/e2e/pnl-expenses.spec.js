import { expect, test } from "@playwright/test";

async function openPnl(page, { role = "admin", failSave = false, failRead = false } = {}) {
  const saved = [];
  await page.addInitScript(() => sessionStorage.setItem("bormostats_api_key", "test-pnl-key"));
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    let body = { items: [] };
    let status = 200;
    if (path.endsWith("/users/me")) body = { role, auth_method: "user_key", name: "Test" };
    if (path.endsWith("/accounts")) body = [];
    if (path.endsWith("/pnl")) body = [];
    if (path.endsWith("/pnl/expenses")) {
      body = saved;
      if (req.method() === "POST") {
        expect(req.headers()["x-api-key"]).toBe("test-pnl-key");
        if (failSave) { status = 500; body = { detail: "Storage unavailable" }; }
        else {
          body = { expense_id: `expense-${saved.length}`, ...req.postDataJSON() };
          saved.push(body);
          status = 201;
        }
      } else if (failRead) { status = 503; body = { detail: "Read unavailable" }; }
    }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("#/pnl");
  return saved;
}

test("manual expense is saved, shown immediately, and survives reload", async ({ page }) => {
  const saved = await openPnl(page);
  const form = page.getByRole("form", { name: "Добавить внешний расход" });
  await form.getByLabel("Дата расхода").fill("2026-10-29");
  await form.getByLabel("Категория", { exact: true }).fill("  Аренда  ");
  await form.getByLabel("Сумма, ₽").fill("12 345,67");
  await form.getByLabel("Комментарий (необязательно)").fill("Склад за октябрь");
  await form.getByRole("button", { name: "Добавить расход", exact: true }).click();
  await expect(form.getByRole("status")).toContainText("Расход сохранён");
  expect(saved).toEqual([{ expense_id: "expense-0", expense_date: "2026-10-29", category: "Аренда", amount_rub: 12345.67, description: "Склад за октябрь" }]);
  await expect(page.getByText("Склад за октябрь", { exact: true })).toBeVisible();
  await expect(form.getByLabel("Сумма, ₽")).toHaveValue("");
  await expect(form.getByLabel("Дата расхода")).toHaveValue("2026-10-29");
  await page.reload();
  await expect(page.getByText("Склад за октябрь", { exact: true })).toBeVisible();
});

test("invalid amounts and blank categories are not sent", async ({ page }) => {
  const saved = await openPnl(page);
  await page.getByLabel("Категория", { exact: true }).fill("Аренда");
  for (const value of ["-1", "0", "1,234", "abc"]) {
    await page.getByLabel("Сумма, ₽").fill(value);
    await page.getByRole("button", { name: "Добавить расход", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Укажите сумму больше нуля");
  }
  await page.getByLabel("Категория", { exact: true }).fill("   ");
  await page.getByLabel("Сумма, ₽").fill("100");
  await page.getByRole("button", { name: "Добавить расход", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Укажите категорию");
  expect(saved).toHaveLength(0);
});

test("save failure preserves input for retry", async ({ page }) => {
  const saved = await openPnl(page, { failSave: true });
  await page.getByLabel("Категория", { exact: true }).fill("Зарплата");
  await page.getByLabel("Сумма, ₽").fill("10000");
  await page.getByRole("button", { name: "Добавить расход", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Не удалось сохранить расход");
  await expect(page.getByLabel("Сумма, ₽")).toHaveValue("10000");
  await expect(page.getByLabel("Категория", { exact: true })).toHaveValue("Зарплата");
  await expect(page.getByRole("button", { name: "Добавить расход", exact: true })).toBeEnabled();
  expect(saved).toHaveLength(0);
});

test("manager can view expenses but cannot enter them", async ({ page }) => {
  await openPnl(page, { role: "manager" });
  await expect(page.getByText("Внешние расходы может добавлять администратор организации.")).toBeVisible();
  await expect(page.getByRole("form", { name: "Добавить внешний расход" })).toHaveCount(0);
});

test("read failure is shown instead of silently claiming no data", async ({ page }) => {
  await openPnl(page, { failRead: true });
  await expect(page.getByRole("alert")).toContainText("Расходы: HTTP 503");
});
