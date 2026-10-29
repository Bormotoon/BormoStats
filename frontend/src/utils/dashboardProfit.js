// P&L and indirect expenses are monthly; never present them as daily figures.
export function dashboardProfit(rows, { dateFrom, dateTo, marketplace = "", accountId = "" }) {
  const selected = rows.filter((row) => row.month.slice(0, 7) >= dateFrom.slice(0, 7)
    && row.month.slice(0, 7) <= dateTo.slice(0, 7)
    && (!row.marketplace || ((!marketplace || row.marketplace === marketplace)
      && (!accountId || row.account_id === accountId))));
  const trading = selected.filter((row) => row.marketplace);
  const confirmed = trading.length > 0 && trading.every((row) => row.tax_enabled
    && row.tax_status === "confirmed" && row.net_profit_rub != null);
  const calculated = trading.length > 0 && trading.every((row) => row.tax_enabled
    && ["confirmed", "estimated"].includes(row.tax_status) && row.net_profit_rub != null);
  return {
    available: selected.length > 0,
    confirmed,
    calculated,
    estimated: calculated && !confirmed,
    net: selected.reduce((total, row) => total + (row.net_profit_rub ?? 0), 0),
    beforeTax: selected.reduce((total, row) => total + (row.profit_before_tax_rub ?? row.net_profit_rub ?? 0), 0),
    expenses: selected.reduce((total, row) => total + (row.additional_expenses_rub || 0), 0),
  };
}
