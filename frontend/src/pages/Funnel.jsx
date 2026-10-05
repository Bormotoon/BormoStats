import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import ExportButton from "../components/ExportButton.jsx";
import { requestAll } from "../utils/api.js";
import { sum, ratio, groupSeries, commonParams, numberFmt, percentFmt, isoDay, DEFAULT_DATE_FROM_OFFSET } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function Funnel() {
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
    requestAll("/api/v1/funnel/daily", { query: params })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message={t("funnel.empty")} />;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <ExportButton dataset="funnel_daily" filters={filters} includeDates={true} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <MetricCard label={t("funnel.views")} value={numberFmt(sum(rows, "views"))} />
        <MetricCard label={t("funnel.addsToCart")} value={numberFmt(sum(rows, "adds_to_cart"))} />
        <MetricCard label={t("funnel.orders")} value={numberFmt(sum(rows, "orders"))} accent="success" />
        <MetricCard label={t("funnel.avgCrOrder")} value={percentFmt(ratio(rows, "orders", "views"))} subvalue={t("funnel.crHint")} />
        <MetricCard label={t("funnel.avgCrCart")} value={percentFmt(ratio(rows, "adds_to_cart", "views"))} subvalue={t("funnel.crHint")} />
        <MetricCard label={t("common.rows")} value={numberFmt(rows.length)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3">
        <div className="lg:col-span-4">
          <AreaChartCard title={t("funnel.ordersByDay")} data={groupSeries(rows, "day", "orders")} dataKey="value" name={t("funnel.orders")} color="var(--color-success)" />
        </div>
        <MetricCard label={t("funnel.conversionRate")} value={percentFmt(ratio(rows, "orders", "adds_to_cart"))} accent="success" />
      </div>

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("funnel.funnelDaily")}</h3>
        <DataTable rows={rows} preferredColumns={["day", "marketplace", "account_id", "product_id", "views", "adds_to_cart", "orders", "cr_order", "cr_cart"]} />
      </section>
    </div>
  );
}
