import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll } from "../utils/api.js";
import { usePageFilters } from "../utils/usePageFilters.js";
import { sum, moneyFmt } from "../utils/formats.js";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";

export default function Taxes() {
  const { t } = useI18n();
  const { searchParams, query, period, dateFrom, dateTo } = usePageFilters();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    requestAll("/api/v1/finance/daily", { query })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message={t("taxes.empty")} />;

  const income = sum(rows, "payout") || sum(rows, "revenue") || 0;
  const usn = income * 0.06;
  const over300k = income > 300000 ? (income - 300000) * 0.01 : 0;
  const fixed = 0;
  const total = usn + over300k + fixed;

  const summary = [{ period, income, usn, over300k, fixed, total }];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="md3-card-elevated p-4"><div className="text-xs text-[var(--color-on-surface-variant)]">Налогооблагаемая база</div><div className="text-lg font-semibold">{moneyFmt(income)}</div></div>
        <div className="md3-card-elevated p-4"><div className="text-xs text-[var(--color-on-surface-variant)]">УСН 6%</div><div className="text-lg font-semibold">{moneyFmt(usn)}</div></div>
        <div className="md3-card-elevated p-4"><div className="text-xs text-[var(--color-on-surface-variant)]">Взносы 1% свыше 300000</div><div className="text-lg font-semibold">{moneyFmt(over300k)}</div></div>
        <div className="md3-card-elevated p-4"><div className="text-xs text-[var(--color-on-surface-variant)]">Итого налоги</div><div className="text-lg font-semibold">{moneyFmt(total)}</div></div>
      </div>
      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">Сводная таблица</h3>
        <DataTable rows={summary} preferredColumns={["period","income","usn","over300k","fixed","total"]} exportName={`Налоги ${period}`} />
      </section>
    </div>
  );
}
