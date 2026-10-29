import { useState, useEffect } from "react";
import OzonFunnel from "./OzonFunnel.jsx";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll } from "../utils/api.js";
import { usePageFilters } from "../utils/usePageFilters.js";
import { sum, ratio, groupSeries, numberFmt, percentFmt, periodLabel } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function Funnel() {
  const { marketplace, accountId, query, period } = usePageFilters();
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = marketplace === "ozon" ? "ozon" : "wb";
  function selectMarketplace(nextMarketplace) {
    const next = new URLSearchParams(searchParams);
    if (nextMarketplace !== marketplace) next.delete("accountId");
    next.set("marketplace", nextMarketplace);
    setSearchParams(next);
  }
  return <div className="space-y-4">
    <div role="group" aria-label="Площадка воронки" className="flex flex-wrap gap-2">
      {[["wb", "Wildberries"], ["ozon", "Ozon"]].map(([id, label]) => <button
        key={id} type="button" aria-pressed={selected === id}
        onClick={() => selectMarketplace(id)}
        className={`px-4 py-2 rounded-full border text-sm font-semibold transition-colors ${selected === id ? "bg-[var(--color-primary)] border-[var(--color-primary)] text-white" : "border-[var(--color-outline-variant)] hover:bg-[var(--color-surface-container)]"}`}
      >{label}</button>)}
    </div>
    {selected === "ozon" ? <OzonFunnel query={query} accountId={accountId} period={period} /> : <WbFunnel />}
  </div>;
}

function WbFunnel() {
  const { t } = useI18n();
  const { searchParams, query, period, dateFrom, dateTo } = usePageFilters();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    requestAll("/api/v1/funnel/daily", { query })
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
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <MetricCard label={t("funnel.views")} value={numberFmt(sum(rows, "views"))} subvalue={period} />
        <MetricCard label={t("funnel.addsToCart")} value={numberFmt(sum(rows, "adds_to_cart"))} subvalue={period} />
        <MetricCard label={t("funnel.orders")} value={numberFmt(sum(rows, "orders"))} subvalue={period} accent="success" />
        <MetricCard label={t("funnel.avgCrOrder")} value={percentFmt(ratio(rows, "orders", "views"))} subvalue={t("funnel.crHint")} />
        <MetricCard label={t("funnel.avgCrCart")} value={percentFmt(ratio(rows, "adds_to_cart", "views"))} subvalue={t("funnel.crHint")} />
        <MetricCard label={t("funnel.conversionRate")} value={percentFmt(ratio(rows, "orders", "adds_to_cart"))} subvalue={period} accent="success" />
      </div>

      <AreaChartCard title={`${t("funnel.ordersByDay")} ${period}`} data={groupSeries(rows, "day", "orders")} dataKey="value" name={t("funnel.orders")} color="var(--color-success)" />

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("funnel.funnelDaily")} {period}</h3>
        <DataTable
          rows={rows}
          preferredColumns={["day", "image_url", "offer_id", "title", "marketplace", "product_id", "views", "adds_to_cart", "orders", "cr_cart", "cr_order"]}
          exportName={`Воронка ${periodLabel(dateFrom, dateTo)}`}
        />
      </section>
    </div>
  );
}
