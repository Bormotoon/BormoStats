import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import { useI18n } from "../utils/i18n.jsx";
import { Funnel as FunnelIcon, X } from "@phosphor-icons/react";
import { isoDay } from "../utils/formats";

const FILTER_CONFIG = {
  dateFrom: { type: "date", defaultValue: () => isoDay(-30) },
  dateTo: { type: "date", defaultValue: () => isoDay(0) },
  marketplace: {
    type: "select",
    options: [
      { value: "", labelKey: "filters.all" },
      { value: "wb", labelKey: "WB" },
      { value: "ozon", labelKey: "Ozon" },
    ],
    defaultValue: "",
  },
  accountId: { type: "text", defaultValue: "" },
  limit: { type: "number", defaultValue: "1000" },
  taskRunsLimit: { type: "number", defaultValue: "200" },
};

export default function FiltersBar({ pageId }) {
  const { t } = useI18n();
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
    if (!value) {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    setSearchParams(next);
  };

  const resetFilters = () => setSearchParams(new URLSearchParams());

  return (
    <div className="mb-4">
      <button
        onClick={() => setShow(!show)}
        className="flex items-center gap-2 text-xs font-semibold text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)] transition-colors mb-2"
      >
        <FunnelIcon size={14} />
        {t("common.settings") === "Settings" ? "Filters" : "Фильтры"}
        {show ? <X size={14} /> : null}
      </button>

      {show && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="overflow-hidden"
        >
          <div className="flex flex-wrap gap-3 p-3 rounded-xl border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)]">
            {activeFilters.map((key) => {
              const config = FILTER_CONFIG[key];
              return (
                <label key={key} className="flex flex-col gap-1 min-w-[140px]">
                  <span className="text-xs font-semibold text-[var(--color-on-surface-variant)]">
                    {t(`filters.${key}`)}
                  </span>
                  {config.type === "select" ? (
                    <select
                      value={getValue(key)}
                      onChange={(e) => updateFilter(key, e.target.value)}
                      className="px-2.5 py-1.5 rounded-lg bg-[var(--color-surface)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] focus:outline-none focus:border-[var(--color-primary)]"
                    >
                      {config.options.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.labelKey.startsWith("filters.") ? t(opt.labelKey) : opt.labelKey}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={config.type}
                      value={getValue(key)}
                      onChange={(e) => updateFilter(key, e.target.value)}
                      placeholder={t(`filters.${key}`)}
                      className="px-2.5 py-1.5 rounded-lg bg-[var(--color-surface)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] placeholder:text-[var(--color-on-surface-variant)] focus:outline-none focus:border-[var(--color-primary)]"
                    />
                  )}
                </label>
              );
            })}
            <div className="flex items-end gap-2">
              <button
                onClick={resetFilters}
                className="px-3 py-1.5 rounded-lg border border-[var(--color-outline-variant)] text-xs font-semibold text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)] transition-colors"
              >
                {t("filters.reset")}
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
}
