import { useMemo } from "react";

export default function DataTable({ rows, preferredColumns }) {
  const columns = useMemo(() => {
    if (!rows.length) return [];
    if (preferredColumns?.length) {
      return preferredColumns.filter((col) =>
        rows.some((row) => Object.prototype.hasOwnProperty.call(row, col))
      );
    }
    return Object.keys(rows[0]);
  }, [rows, preferredColumns]);

  if (!rows.length) {
    return (
      <div className="rounded-xl border border-dashed border-[var(--color-outline-variant)] text-[var(--color-on-surface-variant)] text-center py-12 px-4">
        <p className="text-sm">No data</p>
      </div>
    );
  }

  return (
    <div className="overflow-auto rounded-xl border border-[var(--color-outline-variant)]">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="bg-[var(--color-surface-container)]">
            {columns.map((col) => (
              <th
                key={col}
                className="text-left px-4 py-2.5 text-[11px] font-semibold text-[var(--color-on-surface-variant)] tracking-wide uppercase sticky top-0 bg-[var(--color-surface-container)] z-10"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-outline-variant)]">
          {rows.map((row, i) => (
            <tr
              key={i}
              className="hover:bg-[var(--color-surface-container)]/60 transition-colors"
            >
              {columns.map((col) => (
                <td key={col} className="px-4 py-2 text-[var(--color-on-surface)]">
                  <CellValue column={col} value={row[col]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CellValue({ column, value }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-[var(--color-on-surface-variant)]">-</span>;
  }

  const key = column.toLowerCase();

  if (typeof value === "number") {
    if (["revenue", "cost", "payout", "amount", "orders_sum", "price"].some((t) => key.includes(t))) {
      return <span className="font-mono">{value.toLocaleString("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 2 })}</span>;
    }
    if (["acos", "romi", "cr_", "conversion"].some((t) => key.includes(t))) {
      return <span className="font-mono">{(value * 100).toFixed(2)}%</span>;
    }
    if (Number.isInteger(value)) {
      return <span className="font-mono">{value.toLocaleString("ru-RU")}</span>;
    }
    return <span className="font-mono">{value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}</span>;
  }

  if (typeof value === "string" && key.includes("meta_json")) {
    const text = value.length > 240 ? `${value.slice(0, 240)}...` : value;
    return <span className="font-mono text-xs">{text}</span>;
  }

  return <span>{String(value)}</span>;
}
