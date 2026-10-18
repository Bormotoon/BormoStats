import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll } from "../utils/api.js";
import { usePageFilters } from "../utils/usePageFilters.js";
import { sum, groupSeriesMulti, moneyFmt, numberFmt, periodLabel } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export const SALES_COLUMNS = ["day", "image_url", "offer_id", "title", "marketplace", "product_id", "qty", "revenue", "returns_qty", "payout"];

export default function Sales() {
  const { t } = useI18n();
  const { searchParams, query, period, dateFrom, dateTo } = usePageFilters();
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

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard label={t("sales.revenue")} value={moneyFmt(sum(rows, "revenue"))} subvalue={`${t("sales.revenueHint")}, ${period}`} accent="success" />
        <MetricCard label={t("sales.qty")} value={`${numberFmt(sum(rows, "qty"))} шт`} subvalue={`${t("sales.qtyHint")} ${period}`} />
        <MetricCard label={t("sales.returns")} value={`${numberFmt(sum(rows, "returns_qty"))} шт`} subvalue={`${t("sales.returnsHint")} ${period}`} accent="warning" />
        <MetricCard label={t("sales.payout")} value={moneyFmt(sum(rows, "payout"))} subvalue={`${t("sales.payoutHint")}; ${period}`} />
      </div>

      <AreaChartCard
        title={`${t("sales.revenueByDay")} ${period}`}
        data={groupSeriesMulti(rows, "day", ["revenue", "payout"])}
        series={[
          { dataKey: "revenue", name: t("sales.revenue"), color: "var(--color-primary)" },
          { dataKey: "payout", name: t("sales.payoutByDay"), color: "var(--color-success)" },
        ]}
        currency
      />

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("sales.salesDaily")} {period}</h3>
        <DataTable rows={rows} preferredColumns={SALES_COLUMNS} exportName={`Продажи ${periodLabel(dateFrom, dateTo)}`} />
      </section>
    </div>
  );
}
