import test from "node:test";
import assert from "node:assert/strict";
import { dashboardProfit } from "./dashboardProfit.js";

const scope = { dateFrom: "2026-09-15", dateTo: "2026-09-30", marketplace: "ozon", accountId: "a" };
const row = { month: "2026-09", marketplace: "ozon", account_id: "a", tax_enabled: true, tax_status: "confirmed", net_profit_rub: 800, profit_before_tax_rub: 1000 };
test("includes organization expenses once and scopes trading rows and months", () => {
  const result = dashboardProfit([row, { ...row, account_id: "b" }, { ...row, month: "2026-08" },
    { month: "2026-09", marketplace: "", net_profit_rub: -100, additional_expenses_rub: 100 }], scope);
  assert.equal(result.net, 700);
  assert.equal(result.beforeTax, 900);
  assert.equal(result.expenses, 100);
  assert.equal(result.confirmed, true);
});
test("does not confirm missing tax or an empty period", () => {
  assert.equal(dashboardProfit([{ ...row, tax_status: "missing_report", net_profit_rub: null }], scope).confirmed, false);
  assert.equal(dashboardProfit([{ ...row, tax_enabled: false }], scope).confirmed, false);
  assert.equal(dashboardProfit([], scope).confirmed, false);
});
test("shows estimates and then switches to confirmed report", () => {
  const estimated = dashboardProfit([{ ...row, tax_status: "estimated" }], scope);
  assert.equal(estimated.calculated, true);
  assert.equal(estimated.estimated, true);
  const confirmed = dashboardProfit([row], scope);
  assert.equal(confirmed.calculated, true);
  assert.equal(confirmed.estimated, false);
});
