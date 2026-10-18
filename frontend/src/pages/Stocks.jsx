import { useState, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { requestAll } from "../utils/api.js";
import { sum, numberFmt, ruDate, marketplaceName } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { BarChartCard } from "../components/Chart.jsx";
import { Spinner, EmptyState } from "../components/StatusChip.jsx";

// a product with this many units or fewer on a marketplace is highlighted
export const LOW_STOCK_UNITS = 5;

export default function Stocks() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const query = { marketplace: searchParams.get("marketplace") || "", account_id: searchParams.get("accountId") || "" };
    requestAll("/api/v1/stocks/current", { query })
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [searchParams]);

  const rows = data?.items || [];

  // units per product on its marketplace, over every warehouse
  const productTotals = useMemo(() => {
    const totals = new Map();
    for (const r of rows) {
      const key = `${r.marketplace}|${r.product_id}`;
      const cur = totals.get(key) || { marketplace: r.marketplace, offer_id: r.offer_id, title: r.title, units: 0 };
      cur.units += Number(r.stock_end || 0);
      totals.set(key, cur);
    }
    return totals;
  }, [rows]);

  const warehouses = useMemo(() => {
    const byWarehouse = new Map();
    for (const r of rows) {
      const key = `${r.marketplace}|${r.warehouse_name || r.warehouse_id || ""}`;
      const cur = byWarehouse.get(key) || { marketplace: r.marketplace, warehouse_name: r.warehouse_name || String(r.warehouse_id ?? "—"), units: 0, products: new Set() };
      cur.units += Number(r.stock_end || 0);
      if (Number(r.stock_end || 0) > 0) cur.products.add(r.product_id);
      byWarehouse.set(key, cur);
    }
    return [...byWarehouse.values()]
      .map((w) => ({ ...w, products: w.products.size }))
      .sort((a, b) => b.units - a.units);
  }, [rows]);

  if (loading) return <Spinner />;
  if (error) return <div className="rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error-container)] p-4 text-sm text-[var(--color-error)]">{error}</div>;
  if (!rows.length) return <EmptyState message={t("stocks.empty")} />;

  const isLow = (row) => (productTotals.get(`${row.marketplace}|${row.product_id}`)?.units ?? 0) <= LOW_STOCK_UNITS;
  const lowProducts = [...productTotals.values()].filter((p) => p.units <= LOW_STOCK_UNITS).length;
  const topStock = [...productTotals.values()]
    .sort((a, b) => b.units - a.units)
    .slice(0, 15)
    .map((p) => ({ label: p.offer_id || "—", value: p.units, title: p.title, marketplace: p.marketplace }));
  const asOf = rows[0]?.day;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          label={t("stocks.totalStock")}
          value={`${numberFmt(sum(rows, "stock_end"))} шт`}
          subvalue={`${t("stocks.asOf")} ${ruDate(asOf)} · ${numberFmt(productTotals.size)} ${t("stocks.products")}`}
          className="col-span-2"
        />
        {["wb", "ozon"].map((mp) => {
          const mpRows = rows.filter((r) => r.marketplace === mp);
          if (!mpRows.length) return null;
          return <MetricCard key={mp} label={`${t("stocks.totalStock")} ${marketplaceName(mp)}`} value={`${numberFmt(sum(mpRows, "stock_end"))} шт`} subvalue={`${t("stocks.warehousesWithStock")}: ${new Set(mpRows.filter((r) => Number(r.stock_end) > 0).map((r) => r.warehouse_name)).size}`} />;
        })}
      </div>

      <BarChartCard
        title={t("stocks.topByStock")}
        subtitle={t("stocks.topByStockHint")}
        data={topStock}
        dataKey="value"
        name={t("stocks.units")}
        unit="шт"
        categorical
        labelText={(label, row) => `${label} · ${marketplaceName(row?.marketplace)}${row?.title ? ` — ${row.title}` : ""}`}
        color="var(--color-primary)"
      />

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("stocks.byWarehouse")}</h3>
        <DataTable
          rows={warehouses}
          minWidth={480}
          maxHeight="40vh"
          exportName="Остатки по складам"
          columns={[
            { key: "marketplace", label: t("columns.marketplace") },
            { key: "warehouse_name", label: t("columns.warehouse_name") },
            { key: "units", label: t("columns.stock_end"), type: "number" },
            { key: "products", label: t("stocks.productsInStock"), type: "number" },
          ]}
        />
      </section>

      <section className="md3-card-elevated p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
          <h3 className="text-sm font-semibold text-[var(--color-on-surface)]">{t("stocks.currentStocks")}</h3>
          <p className="text-xs text-[var(--color-on-surface-variant)] flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-sm bg-[var(--color-error-container)] border border-[var(--color-error)]/40" aria-hidden="true" />
            {t("stocks.lowHighlight")} ({numberFmt(lowProducts)})
          </p>
        </div>
        <DataTable
          rows={rows}
          preferredColumns={["day", "image_url", "offer_id", "title", "marketplace", "product_id", "warehouse_name", "stock_end"]}
          exportName={`Остатки ${ruDate(asOf)}`}
          rowClassName={(row) => (isLow(row) ? "bg-[var(--color-error-container)]/60" : "")}
        />
      </section>
    </div>
  );
}
