import { useMemo, useState } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { isMoneyColumn, isPercentColumn, marketplaceName, ruDate } from "../utils/formats.js";
import { downloadXlsx } from "../utils/xlsx.js";
import { CaretDown, CaretUp, FileXls, X } from "@phosphor-icons/react";

const PAGE = 200;

/**
 * A column: { key, label?, type?, value?(row), render?(row), exportable?, align?, width? }.
 * `type` is "date" | "image" | "money" | "percent" | "number" | "text" (inferred from the key
 * when left out); `value` gives the raw value filtered, sorted and exported (row[key] by
 * default); `render` draws the cell.
 */
function inferType(key, sample) {
  const k = key.toLowerCase();
  if (k === "day" || k === "date" || k.endsWith("_day") || k.endsWith("_date")) return "date";
  if (k === "image_url") return "image";
  if (typeof sample === "number") {
    if (isMoneyColumn(k)) return "money";
    if (isPercentColumn(k)) return "percent";
    return "number";
  }
  return "text";
}

function normalizeColumns(columns, rows, t) {
  return columns
    .map((col) => (typeof col === "string" ? { key: col } : col))
    .filter((col) => col.value || col.render || rows.some((row) => Object.prototype.hasOwnProperty.call(row, col.key)))
    .map((col) => {
      const sample = rows.find((row) => row[col.key] !== null && row[col.key] !== undefined)?.[col.key];
      const type = col.type || inferType(col.key, sample);
      const label = col.label ?? (t(`columns.${col.key}`) === `columns.${col.key}` ? col.key : t(`columns.${col.key}`));
      const value = col.value || (col.key === "marketplace" ? (row) => marketplaceName(row.marketplace) : (row) => row[col.key]);
      return { ...col, type, label, value, exportable: col.exportable ?? type !== "image" };
    });
}

/** The text a cell shows, which a text filter matches. */
function displayText(col, raw) {
  if (raw === null || raw === undefined || raw === "") return "";
  if (col.type === "date") return ruDate(raw);
  if (col.type === "money" || col.type === "number") return Number(raw).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
  if (col.type === "percent") return (Number(raw) * 100).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
  return String(raw);
}

function parseNum(text) {
  const num = Number(String(text).replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(num) ? num : null;
}

/**
 * A filter for one column. Numbers take "> 100", "<= 5", "10-20" or "10..20"; percentages
 * are typed as shown (12 for 12%); any other text matches as a substring of what the cell
 * shows, case-insensitively ("10.2026" keeps October's dates).
 */
export function makeMatcher(col, query) {
  const q = query.trim();
  if (!q) return null;
  if (["money", "number", "percent"].includes(col.type)) {
    const scale = col.type === "percent" ? 100 : 1;
    const op = /^(>=|<=|>|<|=)\s*(-?[\d\s.,]+)$/.exec(q);
    if (op) {
      const bound = parseNum(op[2]);
      if (bound !== null) {
        return (raw) => {
          if (raw === null || raw === undefined || raw === "") return false;
          const v = Number(raw) * scale;
          return { ">": v > bound, "<": v < bound, ">=": v >= bound, "<=": v <= bound, "=": Math.abs(v - bound) < 1e-9 }[op[1]];
        };
      }
    }
    const range = /^(-?[\d\s,.]+?)\s*(?:\.\.|–|—|-)\s*(-?[\d\s,.]+)$/.exec(q);
    if (range) {
      const lo = parseNum(range[1]);
      const hi = parseNum(range[2]);
      if (lo !== null && hi !== null) {
        return (raw) => raw !== null && raw !== undefined && raw !== "" && Number(raw) * scale >= lo && Number(raw) * scale <= hi;
      }
    }
  }
  const needle = q.toLowerCase();
  return (raw) => displayText(col, raw).toLowerCase().includes(needle);
}

function compare(a, b) {
  const emptyA = a === null || a === undefined || a === "";
  const emptyB = b === null || b === undefined || b === "";
  if (emptyA || emptyB) return emptyA === emptyB ? 0 : emptyA ? 1 : -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "ru", { numeric: true });
}

const EXPORT_TYPE = { date: "date", money: "money", percent: "percent", number: "number", text: "text" };

/**
 * A table with a filter under every column header, sorting by a header click and a download
 * of the shown (filtered and sorted) rows as an Excel file when `exportName` is given.
 * `rowKey(row)` keeps a row's cells (an input being edited) with the row when it moves.
 */
export default function DataTable({
  rows,
  columns,
  preferredColumns,
  exportName,
  filterable = true,
  rowClassName,
  rowKey,
  maxHeight = "70vh",
  minWidth = 640,
  footer,
}) {
  const { t } = useI18n();
  const [filters, setFilters] = useState({});
  const [sort, setSort] = useState({ key: null, dir: 1 });
  const [shown, setShown] = useState(PAGE);

  const cols = useMemo(() => {
    const spec = columns || preferredColumns || (rows.length ? Object.keys(rows[0]) : []);
    return normalizeColumns(spec, rows, t);
  }, [rows, columns, preferredColumns, t]);

  const visible = useMemo(() => {
    const matchers = cols
      .map((col) => [col, makeMatcher(col, filters[col.key] || "")])
      .filter(([, match]) => match);
    let out = matchers.length ? rows.filter((row) => matchers.every(([col, match]) => match(col.value(row)))) : rows;
    const sortCol = cols.find((col) => col.key === sort.key);
    if (sortCol) out = [...out].sort((a, b) => compare(sortCol.value(a), sortCol.value(b)) * sort.dir);
    return out;
  }, [rows, cols, filters, sort]);

  const hasFilters = Object.values(filters).some((v) => v && v.trim());

  if (!rows.length) {
    return (
      <div className="rounded-xl border border-dashed border-[var(--color-outline-variant)] text-[var(--color-on-surface-variant)] text-center py-12 px-4">
        <p className="text-sm">{t("common.noData")}</p>
      </div>
    );
  }

  const toggleSort = (key) =>
    setSort((s) => (s.key !== key ? { key, dir: 1 } : s.dir === 1 ? { key, dir: -1 } : { key: null, dir: 1 }));

  const exportRows = () => {
    const exported = cols.filter((col) => col.exportable);
    downloadXlsx(
      exportName,
      exportName,
      exported.map((col) => ({ label: col.label, type: EXPORT_TYPE[col.type] || "text", width: col.width })),
      visible.map((row) => exported.map((col) => col.value(row)))
    );
  };

  return (
    <div className="space-y-2">
      {(exportName || (filterable && hasFilters)) && (
        <div className="flex flex-wrap items-center justify-end gap-2 text-xs text-[var(--color-on-surface-variant)]">
          {hasFilters && (
            <>
              <span>
                {t("table.shown")} {visible.length.toLocaleString("ru-RU")} {t("table.of")} {rows.length.toLocaleString("ru-RU")}
              </span>
              <button
                type="button"
                onClick={() => setFilters({})}
                className="flex items-center gap-1 px-2 py-1 rounded-full border border-[var(--color-outline-variant)] hover:bg-[var(--color-surface-container)]"
              >
                <X size={12} /> {t("table.resetFilters")}
              </button>
            </>
          )}
          {exportName && (
            <button
              type="button"
              onClick={exportRows}
              disabled={!visible.length}
              className="flex items-center gap-1 px-3 py-1.5 rounded-full border border-[var(--color-outline-variant)] text-sm font-medium text-[var(--color-on-surface)] hover:bg-[var(--color-surface-container)] disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
            >
              <FileXls size={16} aria-hidden="true" /> {t("table.excel")}
            </button>
          )}
        </div>
      )}
      <div className="overflow-auto rounded-xl border border-[var(--color-outline-variant)]" style={{ maxHeight }}>
        <table className="w-full text-sm" style={{ minWidth }}>
          <thead className="sticky top-0 z-10 bg-[var(--color-surface-container)]">
            <tr>
              {cols.map((col) => {
                const sorted = sort.key === col.key;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={sorted ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                    className="px-3 pt-2.5 pb-1 text-center align-bottom text-[11px] font-semibold text-[var(--color-on-surface-variant)] tracking-wide uppercase"
                  >
                    {col.type === "image" ? (
                      col.label
                    ) : (
                      <button
                        type="button"
                        onClick={() => toggleSort(col.key)}
                        className="inline-flex items-center gap-1 uppercase hover:text-[var(--color-on-surface)]"
                      >
                        {col.label}
                        {sorted && (sort.dir === 1 ? <CaretUp size={10} weight="bold" /> : <CaretDown size={10} weight="bold" />)}
                      </button>
                    )}
                  </th>
                );
              })}
            </tr>
            {filterable && (
              <tr>
                {cols.map((col) => (
                  <th key={col.key} className="px-2 pb-2 font-normal">
                    {col.type !== "image" && (
                      <input
                        type="search"
                        value={filters[col.key] || ""}
                        onChange={(e) => {
                          setFilters((f) => ({ ...f, [col.key]: e.target.value }));
                          setShown(PAGE);
                        }}
                        aria-label={`${t("table.filter")}: ${col.label}`}
                        placeholder={["money", "number", "percent"].includes(col.type) ? "> 0" : t("table.filter")}
                        className="w-full min-w-[64px] px-2 py-1 rounded-md border border-[var(--color-outline-variant)] bg-[var(--color-surface)] text-xs text-[var(--color-on-surface)] placeholder:text-[var(--color-on-surface-variant)]/70 focus:outline-none focus:border-[var(--color-primary)]"
                      />
                    )}
                  </th>
                ))}
              </tr>
            )}
          </thead>
          <tbody className="divide-y divide-[var(--color-outline-variant)]">
            {visible.slice(0, shown).map((row, i) => (
              <tr key={rowKey ? rowKey(row) : i} className={`hover:bg-[var(--color-surface-container)]/60 transition-colors ${rowClassName?.(row) || ""}`}>
                {cols.map((col) => (
                  <td
                    key={col.key}
                    className={`px-3 py-2 text-[var(--color-on-surface)] ${col.align ? `text-${col.align}` : col.type === "text" ? "text-left" : col.type === "date" || col.type === "image" ? "text-center" : "text-right"}`}
                  >
                    {col.render ? col.render(row) : <CellValue type={col.type} value={col.value(row)} />}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          {footer}
        </table>
        {!visible.length && <p className="text-center text-sm py-6 text-[var(--color-on-surface-variant)]">{t("table.nothingFound")}</p>}
      </div>
      {visible.length > shown && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => setShown((n) => n + PAGE * 5)}
            className="px-4 py-1.5 rounded-full border border-[var(--color-outline-variant)] text-sm hover:bg-[var(--color-surface-container)]"
          >
            {t("table.showMore")} ({(visible.length - shown).toLocaleString("ru-RU")})
          </button>
        </div>
      )}
    </div>
  );
}

export function CellValue({ type, value }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-[var(--color-on-surface-variant)]">&mdash;</span>;
  }
  if (type === "image") {
    return <img src={value} alt="" loading="lazy" referrerPolicy="no-referrer" className="inline-block h-12 w-9 rounded object-cover" />;
  }
  if (type === "date") return <span className="whitespace-nowrap font-mono">{ruDate(value)}</span>;
  if (typeof value === "number") {
    if (type === "money") {
      return <span className="font-mono whitespace-nowrap">{value.toLocaleString("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 2 })}</span>;
    }
    if (type === "percent") return <span className="font-mono whitespace-nowrap">{(value * 100).toFixed(2)}%</span>;
    return <span className="font-mono whitespace-nowrap">{value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}</span>;
  }
  const text = String(value);
  return <span>{text.length > 240 ? `${text.slice(0, 240)}…` : text}</span>;
}
