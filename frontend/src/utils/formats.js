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

/** "2026-09-30" (or a timestamp starting with it) as "30.09.2026"; anything else as is. */
export function ruDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
  return match ? `${match[3]}.${match[2]}.${match[1]}` : String(value ?? "");
}

/** "06.09.2026 – 05.10.2026": the period a figure covers, for card and table captions. */
export function periodLabel(dateFrom, dateTo) {
  return `${ruDate(dateFrom)} – ${ruDate(dateTo)}`;
}

/** A snapshot time (balances) in Moscow time, as "05.10.2026, 14:00:00". */
export function formatAsOf(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
}

/** An axis tick: digits grouped by thousands, in roubles when `currency`. */
export function axisNumber(value, currency = false) {
  const text = Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: 0 });
  return currency ? `${text} ₽` : text;
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

export function isPercentColumn(key) {
  const keyLower = key.toLowerCase();
  return ["acos", "romi", "cr_", "conversion"].some((t) => keyLower.includes(t));
}

/** "wb" → "WB", "ozon" → "Ozon", "ym" → "Яндекс Маркет"; anything else as is. */
export function marketplaceName(value) {
  const key = String(value ?? "").toLowerCase();
  return { wb: "WB", ozon: "Ozon", ym: "Яндекс Маркет" }[key] || String(value ?? "");
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

/** Rows summed per `byKey` into one point per label carrying every key of `valueKeys`. */
export function groupSeriesMulti(rows, byKey, valueKeys) {
  const grouped = new Map();
  for (const row of rows) {
    const label = String(row[byKey] || "");
    let point = grouped.get(label);
    if (!point) {
      point = { label };
      for (const key of valueKeys) point[key] = 0;
      grouped.set(label, point);
    }
    for (const key of valueKeys) point[key] += Number(row[key] || 0);
  }
  return [...grouped.values()].sort((a, b) => a.label.localeCompare(b.label));
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
