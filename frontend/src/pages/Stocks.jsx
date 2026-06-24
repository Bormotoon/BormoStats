import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { request } from "../utils/api.js";
import { sum, commonParams, moneyFmt, numberFmt } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { BarChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function Stocks() {
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const filters = {
    marketplace: searchParams.get("marketplace") || "",
    accountId: searchParams.get("accountId") || "",
    limit: searchParams.get("limit") || "1000",
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const params = commonParams(filters, false);
    request("/api/v1/stocks/current", { query: params })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message="Нет данных по остаткам" />;

  const lowStock = rows.filter((r) => Number(r.stock_end || 0) <= 5).length;
  const stockByProduct = rows
    .reduce((acc, r) => {
      const key = r.product_id || "unknown";
      acc[key] = (acc[key] || 0) + Number(r.stock_end || 0);
      return acc;
    }, {});
  const topStock = Object.entries(stockByProduct)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
    .map(([label, value]) => ({ label: label.substring(0, 20), value }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard label="Total Stock" value={numberFmt(sum(rows, "stock_end"))} className="col-span-2" />
        <MetricCard label="Rows" value={numberFmt(rows.length)} />
        <MetricCard label="Low Stock (≤5)" value={numberFmt(lowStock)} accent="error" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <div className="lg:col-span-3">
          <BarChartCard title="Top Products by Stock" data={topStock} dataKey="value" name="Units" color="var(--color-primary)" />
        </div>
        <MetricCard label="Warehouses" value={numberFmt(new Set(rows.map((r) => r.warehouse_id)).size)} />
      </div>

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">Current Stocks</h3>
        <DataTable rows={rows} preferredColumns={["day", "marketplace", "account_id", "product_id", "warehouse_id", "stock_end"]} />
      </section>
    </div>
  );
}
