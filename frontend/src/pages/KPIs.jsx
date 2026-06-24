import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { request } from "../utils/api.js";
import { sum, commonParams, moneyFmt, numberFmt, percentFmt } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { BarChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

export default function KPIs() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const filters = {
    marketplace: searchParams.get("marketplace") || "",
    accountId: searchParams.get("accountId") || "",
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const params = commonParams(filters, false);
    request("/api/v1/kpis", { query: params })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>;

  const rows = data?.items || [];
  if (!rows.length) return <EmptyState message={t("kpis.empty")} />;

  const revenueData = rows.map((r) => ({
    label: `${r.marketplace || ""} ${r.account_id || ""}`.trim() || "unknown",
    value: Number(r.revenue_30d || 0),
  }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label={t("kpis.revenue30d")} value={moneyFmt(sum(rows, "revenue_30d"))} accent="success" className="col-span-2" />
        <MetricCard label={t("kpis.qty30d")} value={numberFmt(sum(rows, "qty_30d"))} />
        <MetricCard label={t("kpis.returns30d")} value={numberFmt(sum(rows, "returns_30d"))} accent="warning" />
        <MetricCard label={t("kpis.adsCost30d")} value={moneyFmt(sum(rows, "cost_30d"))} accent="error" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <div className="lg:col-span-3">
          <BarChartCard title={t("kpis.revenueByAccount")} data={revenueData} dataKey="value" name={t("kpis.revenue30d")} />
        </div>
        <MetricCard label={t("kpis.accounts")} value={numberFmt(rows.length)} />
      </div>

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("kpis.kpi30d")}</h3>
        <DataTable rows={rows} preferredColumns={["marketplace", "account_id", "revenue_30d", "qty_30d", "returns_30d", "cost_30d", "acos_30d"]} />
      </section>
    </div>
  );
}
