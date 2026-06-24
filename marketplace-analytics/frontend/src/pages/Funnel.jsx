import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { request } from "../utils/api.js";
import { sum, avg, groupSeries, commonParams, moneyFmt, numberFmt, percentFmt } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function Funnel() {
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const filters = {
    dateFrom: searchParams.get("dateFrom") || (() => { const d = new Date(); d.setUTCDate(d.getUTCDate() - 30); return d.toISOString().slice(0, 10); })(),
    dateTo: searchParams.get("dateTo") || new Date().toISOString().slice(0, 10),
    marketplace: searchParams.get("marketplace") || "",
    accountId: searchParams.get("accountId") || "",
    limit: searchParams.get("limit") || "1000",
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const params = commonParams(filters);
    request("/api/v1/funnel/daily", { query: params })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error)]/10 p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message="Нет данных по воронке за выбранный период" />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard label="Views" value={numberFmt(sum(rows, "views"))} />
        <MetricCard label="Adds to Cart" value={numberFmt(sum(rows, "adds_to_cart"))} />
        <MetricCard label="Orders" value={numberFmt(sum(rows, "orders"))} accent="success" />
        <MetricCard label="Avg CR Order" value={percentFmt(avg(rows, "cr_order"))} accent="blue" />
        <MetricCard label="Avg CR Cart" value={percentFmt(avg(rows, "cr_cart"))} />
        <MetricCard label="Rows" value={numberFmt(rows.length)} />
      </div>
      <AreaChartCard title="Orders by Day" data={groupSeries(rows, "day", "orders")} dataKey="value" name="Orders" color="var(--color-success)" />
      <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
        <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-3">Funnel Daily</h3>
        <DataTable rows={rows} preferredColumns={["day", "marketplace", "account_id", "product_id", "views", "adds_to_cart", "orders", "cr_order", "cr_cart"]} />
      </section>
    </div>
  );
}
