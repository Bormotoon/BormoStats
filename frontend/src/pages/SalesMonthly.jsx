import { useState, useEffect, useMemo } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll } from "../utils/api.js";
import { usePageFilters } from "../utils/usePageFilters.js";
import { moneyFmt, numberFmt } from "../utils/formats.js";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";

export default function SalesMonthly() {
  const { t } = useI18n();
  const { searchParams, query } = usePageFilters();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    requestAll("/api/v1/sales/daily", { query })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message={t("sales.empty")} />;

  const byMonth = {};
  for (const r of rows) {
    const m = (r.day || "").slice(0, 7);
    if (!byMonth[m]) byMonth[m] = { month: m, qty: 0, revenue: 0, returns: 0 };
    byMonth[m].qty += r.qty || 0;
    byMonth[m].revenue += r.revenue || 0;
    byMonth[m].returns += r.returns_qty || 0;
  }
  const items = Object.values(byMonth).sort((a, b) => a.month.localeCompare(b.month));
  const totalQty = items.reduce((s, x) => s + x.qty, 0);
  const totalRev = items.reduce((s, x) => s + x.revenue, 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div className="md3-card-elevated p-4"><div className="text-xs">Месяцев</div><div className="text-lg font-semibold">{items.length}</div></div>
        <div className="md3-card-elevated p-4"><div className="text-xs">Всего продаж</div><div className="text-lg font-semibold">{numberFmt(totalQty)}</div></div>
        <div className="md3-card-elevated p-4"><div className="text-xs">Выручка</div><div className="text-lg font-semibold">{moneyFmt(totalRev)}</div></div>
      </div>
      <section className="md3-card-elevated p-4">
        <DataTable rows={items} preferredColumns={["month","qty","revenue","returns"]} exportName="Продажи по месяцам" />
      </section>
    </div>
  );
}
