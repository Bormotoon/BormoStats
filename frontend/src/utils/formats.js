export function numberFmt(value, digits = 0) {
  const num = Number(value || 0);
  return num.toLocaleString("ru-RU", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export function moneyFmt(value) {
  const num = Number(value || 0);
  return num.toLocaleString("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 2,
  });
}

export function percentFmt(value) {
  return `${numberFmt(value * 100, 2)}%`;
}

/**
 * A date (YYYY-MM-DD) in Moscow, `offsetDays` from today. Analytics days are Moscow days, as
 * in the marketplaces' reports, so a period must end on the Moscow today, not the UTC one.
 */
export function isoDay(offsetDays = 0) {
  const date = new Date(Date.now() + offsetDays * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(date);
}

/** The default period: the last 30 days including today. */
export const DEFAULT_DATE_FROM_OFFSET = -29;

// money columns of the finance block matched by exact name: "returns" as a substring would
// also catch returns_qty
export const MONEY_COLUMNS = new Set([
  "sales", "returns", "commission", "acquiring", "logistics", "reverse_logistics", "storage",
  "acceptance", "penalties", "other", "net_accrued", "opening_balance", "closing_balance",
  "balance", "for_withdraw",
]);

export function isMoneyColumn(key) {
  const keyLower = key.toLowerCase();
  return MONEY_COLUMNS.has(keyLower)
    || ["revenue", "cost", "payout", "amount", "orders_sum", "price"].some((t) => keyLower.includes(t));
}

export function formatCell(key, value) {
  if (value === null || value === undefined || value === "") return "-";
  const keyLower = key.toLowerCase();
  if (typeof value === "number") {
    if (isMoneyColumn(key)) {
      return moneyFmt(value);
    }
    if (["acos", "romi", "cr_", "conversion"].some((t) => keyLower.includes(t))) {
      return percentFmt(value);
    }
    if (Number.isInteger(value)) return numberFmt(value, 0);
    return numberFmt(value, 2);
  }
  if (typeof value === "string" && keyLower.includes("meta_json")) {
    return value.length > 240 ? `${value.slice(0, 240)}...` : value;
  }
  return String(value);
}

export function sum(rows, key) {
  return rows.reduce((acc, row) => acc + Number(row[key] || 0), 0);
}

/**
 * sum(numerator) / sum(denominator) over all rows. Use it for conversion, ACOS or margin:
 * averaging per-row ratios lets a row with 1 view weigh as much as one with 10 000.
 */
export function ratio(rows, numeratorKey, denominatorKey) {
  const denominator = sum(rows, denominatorKey);
  return denominator ? sum(rows, numeratorKey) / denominator : 0;
}

/** Rows summed per key, e.g. one row per product over a period of day × product rows. */
export function totalsBy(rows, keyFn, valueKeys) {
  const grouped = new Map();
  for (const row of rows) {
    const key = keyFn(row);
    let total = grouped.get(key);
    if (!total) {
      total = { ...row };
      for (const valueKey of valueKeys) total[valueKey] = 0;
      grouped.set(key, total);
    }
    for (const valueKey of valueKeys) total[valueKey] += Number(row[valueKey] || 0);
  }
  return [...grouped.values()];
}

export function avg(rows, key) {
  if (!rows.length) return 0;
  return sum(rows, key) / rows.length;
}

export function groupSeries(rows, byKey, valueKey) {
  const grouped = new Map();
  for (const row of rows) {
    const label = String(row[byKey] || "");
    grouped.set(label, (grouped.get(label) || 0) + Number(row[valueKey] || 0));
  }
  return [...grouped.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, value]) => ({ label, value }));
}

export function commonParams(filters, includeDates = true) {
  const params = {
    marketplace: filters.marketplace,
    account_id: filters.accountId,
    limit: Number(filters.limit || 1000),
  };
  if (includeDates) {
    return { ...params, date_from: filters.dateFrom, date_to: filters.dateTo };
  }
  return params;
}
