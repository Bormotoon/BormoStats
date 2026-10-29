import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import DateRangePicker from "./DateRangePicker.jsx";
import { DEFAULT_DATE_FROM_OFFSET, isoDay } from "../utils/formats";

// pages whose figures cover a period; the marketplace is picked in the header
const PERIOD_PAGES = new Set(["dashboard", "sales", "finance", "funnel", "ads", "economics", "pnl"]);

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

  // filter changes replace the history entry, so "Back" leaves the page instead of undoing dates
  const update = (changes) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <span className="text-sm font-semibold text-[var(--color-on-surface-variant)]">
        {t("filters.period")}
      </span>
      <DateRangePicker dateFrom={dateFrom} dateTo={dateTo} onChange={update} />
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
