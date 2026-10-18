import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { CalendarBlank } from "@phosphor-icons/react";
import { DEFAULT_DATE_FROM_OFFSET, isoDay } from "../utils/formats";

// pages whose figures cover a period; the marketplace is picked in the header
const PERIOD_PAGES = new Set(["dashboard", "sales", "finance", "funnel", "ads"]);
// days back from today, today included
const PRESETS = [
  { days: 7, key: "days7" },
  { days: 30, key: "days30" },
  { days: 90, key: "days90" },
  { days: 182, key: "months6" },
  { days: 365, key: "year" },
];

const inputClass =
  "px-2.5 py-1.5 rounded-lg bg-[var(--color-surface)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] focus:outline-none focus:border-[var(--color-primary)]";

/** The period of the page, always on top; the default is the last 30 days. */
export default function FiltersBar({ pageId }) {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();

  if (pageId === "taskRuns") return <TaskRunsLimit searchParams={searchParams} setSearchParams={setSearchParams} t={t} />;
  if (!PERIOD_PAGES.has(pageId)) return null;

  const dateFrom = searchParams.get("dateFrom") || isoDay(DEFAULT_DATE_FROM_OFFSET);
  const dateTo = searchParams.get("dateTo") || isoDay(0);
  const today = isoDay(0);

  // filter changes replace the history entry, so "Back" leaves the page instead of undoing dates
  const update = (changes) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setSearchParams(next, { replace: true });
  };

  const applyPreset = (days) => update({ dateFrom: isoDay(1 - days), dateTo: today });
  const activePreset = dateTo === today ? PRESETS.find((p) => dateFrom === isoDay(1 - p.days))?.days : undefined;

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 p-3 rounded-xl border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)]">
      <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-on-surface)] self-center">
        <CalendarBlank size={16} aria-hidden="true" />
        {t("filters.period")}
      </div>
      <div className="flex flex-wrap gap-1" role="group" aria-label={t("filters.period")}>
        {PRESETS.map((p) => (
          <button
            key={p.days}
            type="button"
            onClick={() => applyPreset(p.days)}
            aria-pressed={activePreset === p.days}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors ${
              activePreset === p.days
                ? "bg-[var(--color-primary)] border-[var(--color-primary)] text-white"
                : "border-[var(--color-outline-variant)] text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)]"
            }`}
          >
            {t(`filters.presets.${p.key}`)}
          </button>
        ))}
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-semibold text-[var(--color-on-surface-variant)]">{t("filters.dateFrom")}</span>
        <input type="date" value={dateFrom} max={dateTo} onChange={(e) => e.target.value && update({ dateFrom: e.target.value })} className={inputClass} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-semibold text-[var(--color-on-surface-variant)]">{t("filters.dateTo")}</span>
        <input type="date" value={dateTo} min={dateFrom} max={today} onChange={(e) => e.target.value && update({ dateTo: e.target.value })} className={inputClass} />
      </label>
    </div>
  );
}

function TaskRunsLimit({ searchParams, setSearchParams, t }) {
  return (
    <div className="mb-4">
      <label className="inline-flex flex-col gap-1">
        <span className="text-xs font-semibold text-[var(--color-on-surface-variant)]">{t("filters.taskRunsLimit")}</span>
        <input
          type="number"
          min="1"
          value={searchParams.get("taskRunsLimit") || "200"}
          onChange={(e) => {
            const next = new URLSearchParams(searchParams);
            next.set("taskRunsLimit", e.target.value || "200");
            setSearchParams(next, { replace: true });
          }}
          className={inputClass}
        />
      </label>
    </div>
  );
}
