import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { request } from "../utils/api.js";
import { sum, groupSeries, commonParams, moneyFmt, numberFmt } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function Sales() {
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
    request("/api/v1/sales/daily", { query: params })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error)]/10 p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message="Нет данных по продажам за выбранный период" />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <MetricCard label="Rows" value={numberFmt(rows.length)} />
        <MetricCard label="Revenue" value={moneyFmt(sum(rows, "revenue"))} accent="success" />
        <MetricCard label="Qty" value={numberFmt(sum(rows, "qty"))} />
        <MetricCard label="Returns" value={numberFmt(sum(rows, "returns_qty"))} accent="warning" />
        <MetricCard label="Payout" value={moneyFmt(sum(rows, "payout"))} />
      </div>
      <AreaChartCard title="Revenue by Day" data={groupSeries(rows, "day", "revenue")} dataKey="value" name="Revenue" />
      <section className="rounded-2xl border border-[var(--color-border)] card-gradient p-4">
        <h3 className="text-sm font-bold text-[var(--color-text-primary)] mb-3">Sales Daily</h3>
        <DataTable rows={rows} preferredColumns={["day", "marketplace", "account_id", "product_id", "qty", "revenue", "returns_qty", "payout"]} />
      </section>
    </div>
  );
}
