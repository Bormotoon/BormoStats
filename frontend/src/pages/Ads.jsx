import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll } from "../utils/api.js";
import { sum, ratio, groupSeries, commonParams, moneyFmt, numberFmt, percentFmt, isoDay, periodLabel, DEFAULT_DATE_FROM_OFFSET } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function Ads() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const filters = {
    dateFrom: searchParams.get("dateFrom") || isoDay(DEFAULT_DATE_FROM_OFFSET),
    dateTo: searchParams.get("dateTo") || isoDay(0),
    marketplace: searchParams.get("marketplace") || "",
    accountId: searchParams.get("accountId") || "",
    limit: searchParams.get("limit") || "1000",
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const params = commonParams(filters);
    requestAll("/api/v1/ads/daily", { query: params })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message={t("ads.empty")} />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label={t("ads.cost")} value={moneyFmt(sum(rows, "cost"))} accent="error" />
        <MetricCard label={t("ads.revenue")} value={moneyFmt(sum(rows, "revenue"))} accent="success" />
        <MetricCard label={t("ads.clicks")} value={numberFmt(sum(rows, "clicks"))} />
        <MetricCard label={t("ads.orders")} value={numberFmt(sum(rows, "orders"))} />
        <MetricCard label={t("ads.avgAcos")} value={percentFmt(ratio(rows, "cost", "revenue"))} subvalue={t("ads.acosHint")} accent="warning" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <div className="lg:col-span-2">
          <AreaChartCard title={t("ads.costByDay")} data={groupSeries(rows, "day", "cost")} dataKey="value" name={t("ads.cost")} color="var(--color-error)" currency />
        </div>
        <div className="lg:col-span-2">
          <AreaChartCard title={t("ads.revenueByDay")} data={groupSeries(rows, "day", "revenue")} dataKey="value" name={t("ads.revenue")} color="var(--color-success)" currency />
        </div>
      </div>

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("ads.adsDaily")}</h3>
        <DataTable rows={rows} exportName={`Реклама ${periodLabel(filters.dateFrom, filters.dateTo)}`} preferredColumns={["day", "marketplace", "campaign_id", "impressions", "clicks", "cost", "orders", "revenue", "acos", "romi"]} />
      </section>
    </div>
  );
}
