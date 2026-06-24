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

export function isoDay(offsetDays) {
  const now = new Date();
  now.setUTCDate(now.getUTCDate() + offsetDays);
  return now.toISOString().slice(0, 10);
}

export function formatCell(key, value) {
  if (value === null || value === undefined || value === "") return "-";
  const keyLower = key.toLowerCase();
  if (typeof value === "number") {
    if (["revenue", "cost", "payout", "amount", "orders_sum", "price"].some((t) => keyLower.includes(t))) {
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
