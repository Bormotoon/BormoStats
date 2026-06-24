import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import { Funnel as FunnelIcon, X } from "@phosphor-icons/react";
import { isoDay } from "../utils/formats";

const FILTER_CONFIG = {
  dateFrom: { label: "Date From", type: "date", defaultValue: () => isoDay(-30) },
  dateTo: { label: "Date To", type: "date", defaultValue: () => isoDay(0) },
  marketplace: {
    label: "Marketplace",
    type: "select",
    options: [
      { value: "", label: "All" },
      { value: "wb", label: "WB" },
      { value: "ozon", label: "Ozon" },
    ],
    defaultValue: "",
  },
  accountId: { label: "Account ID", type: "text", defaultValue: "" },
  limit: { label: "Limit", type: "number", defaultValue: "1000" },
  taskRunsLimit: { label: "Task Runs Limit", type: "number", defaultValue: "200" },
};

export default function FiltersBar({ pageId }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [show, setShow] = useState(false);

  const pageFilters = {
    dashboard: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
    sales: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
    stocks: ["marketplace", "accountId", "limit"],
    funnel: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
    ads: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
    kpis: ["marketplace", "accountId"],
    watermarks: [],
    taskRuns: ["taskRunsLimit"],
    adminActions: [],
    system: [],
  };

  const activeFilters = pageFilters[pageId] || [];

  if (!activeFilters.length) return null;

  const getValue = (key) => {
    const config = FILTER_CONFIG[key];
    return searchParams.get(key) || (config.defaultValue ? config.defaultValue() : "");
  };

  const updateFilter = (key, value) => {
    const next = new URLSearchParams(searchParams);
    if (value === "" || value === null || value === undefined) {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    setSearchParams(next);
  };

  const resetFilters = () => {
    setSearchParams(new URLSearchParams());
  };

  return (
    <div className="mb-4">
      <button
        onClick={() => setShow(!show)}
        className="flex items-center gap-2 text-xs font-semibold text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors mb-2"
      >
        <FunnelIcon size={14} />
        Filters
        {show ? <X size={14} /> : null}
      </button>

      {show && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="overflow-hidden"
        >
          <div className="flex flex-wrap gap-3 p-3 rounded-xl border border-[var(--color-border)] card-gradient">
            {activeFilters.map((key) => {
              const config = FILTER_CONFIG[key];
              return (
                <label key={key} className="flex flex-col gap-1 min-w-[140px]">
                  <span className="text-xs font-semibold text-[var(--color-text-muted)]">
                    {config.label}
                  </span>
                  {config.type === "select" ? (
                    <select
                      value={getValue(key)}
                      onChange={(e) => updateFilter(key, e.target.value)}
                      className="px-2.5 py-1.5 rounded-lg bg-[var(--color-surface)] border border-[var(--color-border)] text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-brand)]"
                    >
                      {config.options.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={config.type}
                      value={getValue(key)}
                      onChange={(e) => updateFilter(key, e.target.value)}
                      placeholder={config.label}
                      className="px-2.5 py-1.5 rounded-lg bg-[var(--color-surface)] border border-[var(--color-border)] text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-brand)]"
                    />
                  )}
                </label>
              );
            })}
            <div className="flex items-end gap-2">
              <button
                onClick={resetFilters}
                className="px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-xs font-semibold text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-highest)] transition-colors"
              >
                Reset
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
}

export function useFilters(pageId) {
  const [searchParams] = useSearchParams();

  const pageFilters = {
    dashboard: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
    sales: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
    stocks: ["marketplace", "accountId", "limit"],
    funnel: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
    ads: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
    kpis: ["marketplace", "accountId"],
    watermarks: [],
    taskRuns: ["taskRunsLimit"],
    adminActions: [],
    system: [],
  };

  const activeFilters = pageFilters[pageId] || [];
  const params = {};

  for (const key of activeFilters) {
    const config = FILTER_CONFIG[key];
    params[key] = searchParams.get(key) || (config.defaultValue ? config.defaultValue() : "");
  }

  const toApiParams = (includeDates = true) => {
    const result = {
      marketplace: params.marketplace || "",
      account_id: params.accountId || "",
      limit: Number(params.limit || 1000),
    };
    if (includeDates && params.dateFrom && params.dateTo) {
      result.date_from = params.dateFrom;
      result.date_to = params.dateTo;
    }
    return result;
  };

  return { params, toApiParams };
}
