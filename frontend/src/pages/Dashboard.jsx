import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { request, requestAll } from "../utils/api.js";
import { sum, groupSeries, totalsBy, moneyFmt, numberFmt, isoDay, periodLabel, formatAsOf, DEFAULT_DATE_FROM_OFFSET } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import StatusChip from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner } from "../components/StatusChip.jsx";
import { ListChecks, WarningCircle, Package, Megaphone } from "@phosphor-icons/react";

export default function Dashboard() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [state, setState] = useState({ loading: true, sales: [], ads: [], stocks: [], kpis: [], tasks: [], finance: [], balance: [], health: null, ready: null, error: "" });

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: "" }));

    const get = (key, def) => searchParams.get(key) || def;
    const dateFrom = get("dateFrom", isoDay(DEFAULT_DATE_FROM_OFFSET));
    const dateTo = get("dateTo", isoDay(0));
    const marketplace = get("marketplace", "");
    const accountId = get("accountId", "");
    const limit = get("limit", "1000");

    const params = { date_from: dateFrom, date_to: dateTo, marketplace, account_id: accountId, limit: Number(limit) };
    const paramsNd = { marketplace, account_id: accountId, limit: Number(limit) };

    Promise.all([
      requestAll("/api/v1/sales/daily", { query: params }).then(r => r.items || []).catch(() => []),
      requestAll("/api/v1/ads/daily", { query: params }).then(r => r.items || []).catch(() => []),
      requestAll("/api/v1/stocks/current", { query: paramsNd }).then(r => r.items || []).catch(() => []),
      request("/api/v1/kpis", { query: paramsNd }).then(r => r.items || []).catch(() => []),
      request("/api/v1/insights/tasks", { query: { status: "open" }, admin: true }).then(r => r || []).catch(() => []),
      requestAll("/api/v1/finance/daily", { query: params }).then(r => r.items || []).catch(() => []),
      requestAll("/api/v1/finance/balance", { query: paramsNd }).then(r => r.items || []).catch(() => []),
      request("/health/live").catch(() => null),
      request("/health/ready").catch(() => null),
    ]).then(([sales, ads, stocks, kpis, tasks, finance, balance, health, ready]) => {
      if (!cancelled) {
        setState({ loading: false, sales, ads, stocks, kpis, tasks, finance, balance, health, ready, error: "" });
      }
    });

    return () => { cancelled = true; };
  }, [searchParams]);

  if (state.loading) return <Spinner />;

  const { sales: salesRows, ads: adsRows, stocks: stockRows, kpis: kpiRows, tasks, health, ready } = state;
  const period = `${t("dashboard.periodFor")} ${periodLabel(
    searchParams.get("dateFrom") || isoDay(DEFAULT_DATE_FROM_OFFSET),
    searchParams.get("dateTo") || isoDay(0),
  )}`;
  // one row per product over the whole period, not the best product-days
  const topProducts = totalsBy(salesRows, (r) => `${r.marketplace}|${r.account_id}|${r.product_id}`, ["qty", "revenue", "returns_qty", "payout"])
    .sort((a, b) => b.revenue - a.revenue)
    .slice(0, 10)
    .map((row, i) => ({ ...row, rank: i + 1, marketplace: row.marketplace === "wb" ? "WB" : "Ozon" }));

  const taskIcons = { turnover: Package, stagnant: WarningCircle, bad_ad: Megaphone };
  const taskColors = { turnover: "text-blue-600", stagnant: "text-orange-600", bad_ad: "text-red-600" };

  return (
    <div className="space-y-4">
      {tasks.length > 0 && (
        <section className="md3-card-elevated p-4">
          <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3 flex items-center gap-2">
            <ListChecks size={16} weight="fill" className="text-[var(--color-primary)]" />
            Задачи на сегодня ({tasks.length})
          </h3>
          <div className="space-y-2">
            {tasks.slice(0, 5).map((task) => {
              const Icon = taskIcons[task.trigger_type] || ListChecks;
              const color = taskColors[task.trigger_type] || "";
              return (
                <div key={task.task_id} className="flex items-start gap-3 p-2 rounded-lg bg-[var(--color-surface-container)]">
                  <Icon size={18} className={`${color} mt-0.5 shrink-0`} />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-[var(--color-on-surface)]">{task.title}</p>
                    <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5 line-clamp-2">{task.description}</p>
                  </div>
                  <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-semibold ${
                    task.priority === "high" ? "bg-red-100 text-red-700" : "bg-yellow-100 text-yellow-700"
                  }`}>{task.priority}</span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <div className="grid grid-cols-4 md:grid-cols-6 gap-3">
        <MetricCard label={t("common.health")} value={<StatusChip ok={health?.status === "ok"} okText={t("common.healthy")} failText={t("common.unhealthy")} />} subvalue="FastAPI" accent={health?.status === "ok" ? "success" : "error"} />
        <MetricCard label={t("common.ready")} value={<StatusChip ok={ready?.status === "ready"} okText={t("common.readyStatus")} failText={t("common.notReady")} />} subvalue="ClickHouse+Redis" accent={ready?.status === "ready" ? "success" : "error"} />
        <MetricCard label={t("dashboard.revenue")} value={moneyFmt(sum(salesRows, "revenue"))} subvalue={period} className="col-span-2" />
        <MetricCard label={t("dashboard.salesQty")} value={numberFmt(sum(salesRows, "qty"))} subvalue={`${t("dashboard.sumQty")} ${period}`} />
        <MetricCard label={t("dashboard.adCost")} value={moneyFmt(sum(adsRows, "cost"))} subvalue={period} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {state.balance.map((b) => (
          <MetricCard
            key={`${b.marketplace}|${b.account_id}`}
            label={`${t("finance.balance")} ${b.marketplace.toUpperCase()}`}
            value={moneyFmt(b.balance)}
            subvalue={[
              b.for_withdraw !== null && b.for_withdraw !== undefined ? `${t("finance.forWithdraw")}: ${moneyFmt(b.for_withdraw)}` : "",
              `${t("finance.asOf")} ${formatAsOf(b.as_of)}`,
            ].filter(Boolean).join(" · ")}
            accent="success"
          />
        ))}
        <MetricCard label={t("finance.netAccrued")} value={moneyFmt(sum(state.finance, "net_accrued"))} subvalue={period} accent="success" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <MetricCard label={t("dashboard.stockUnits")} value={numberFmt(sum(state.stocks, "stock_end"))} subvalue={`${numberFmt(state.stocks.length)} ${t("dashboard.items")}`} className="lg:col-span-1" />
        <div className="lg:col-span-3">
          <AreaChartCard title={`${t("dashboard.revenueTrend")} ${period}`} data={groupSeries(salesRows, "day", "revenue")} dataKey="value" name={t("dashboard.revenue")} currency />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <div className="lg:col-span-3">
          <AreaChartCard title={`${t("dashboard.adSpendTrend")} ${period}`} data={groupSeries(adsRows, "day", "cost")} dataKey="value" name={t("dashboard.adCost")} color="var(--color-warning)" currency />
        </div>
        <MetricCard label={t("dashboard.stockItems")} value={numberFmt(new Set(state.stocks.map(r => r.product_id)).size)} subvalue={t("dashboard.uniqueProducts")} />
      </div>

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("dashboard.topProducts")} {period}</h3>
        <DataTable rows={topProducts} preferredColumns={["rank", "image_url", "title", "offer_id", "marketplace", "product_id", "qty", "revenue", "returns_qty", "payout"]} />
      </section>
    </div>
  );
}
