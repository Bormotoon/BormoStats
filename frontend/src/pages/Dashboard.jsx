import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../utils/i18n.jsx";
import { request, requestAll } from "../utils/api.js";
import { sum, groupSeries, totalsBy, numberFmt, isoDay, periodLabel, marketplaceName, DEFAULT_DATE_FROM_OFFSET } from "../utils/formats.js";
import MetricCard from "../components/MetricCard.jsx";
import StatusChip from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";
import { balanceCaption } from "./Finance.jsx";
import { AreaChartCard } from "../components/Chart.jsx";
import { Spinner } from "../components/StatusChip.jsx";
import { ListChecks, WarningCircle, Package, Megaphone } from "@phosphor-icons/react";

const moneyFmt = (value) => Number(value || 0).toLocaleString("ru-RU", {
  style: "currency", currency: "RUB", maximumFractionDigits: 0, minimumFractionDigits: 0,
});

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
      requestAll("/api/v1/stocks/current", { query: { ...paramsNd, as_of: dateTo } }).then(r => r.items || []).catch(() => []),
      request("/api/v1/kpis", { query: paramsNd }).then(r => r.items || []).catch(() => []),
      request("/api/v1/insights/tasks", { query: { status: "open" }, admin: true }).then(r => r || []).catch(() => []),
      requestAll("/api/v1/finance/daily", { query: params }).then(r => r.items || []).catch(() => []),
      requestAll("/api/v1/finance/balance", { query: { ...paramsNd, as_of: dateTo } }).then(r => r.items || []).catch(() => []),
      request("/health/live").catch(() => null),
      request("/health/ready").catch(() => null),
      request("/api/v1/pnl/daily", { query: params, admin: true }).catch(() => null),
    ]).then(([sales, ads, stocks, kpis, tasks, finance, balance, health, ready, pnl]) => {
      if (!cancelled) {
        setState({ loading: false, sales, ads, stocks, kpis, tasks, finance, balance, health, ready, pnl, error: "" });
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
  const uncostedStockUnits = sum(stockRows.filter((row) => row.cost_price_rub == null), "stock_end");
  const stockValuationAvailable = stockRows.length > 0 && stockRows.every((row) => Object.hasOwn(row, "stock_cost_rub"));
  const profitFrom = searchParams.get("dateFrom") || isoDay(DEFAULT_DATE_FROM_OFFSET);
  const profitTo = searchParams.get("dateTo") || isoDay(0);
  const daily = state.pnl?.items || [];
  const profit = {
    available: daily.length > 0,
    calculated: daily.length > 0,
    estimated: daily.some((r) => r.tax_status === "estimated"),
    net: sum(daily, "profit"), beforeTax: sum(daily, "before_tax"),
    expenses: sum(daily, "external"),
  };
  const dailyChart = daily.map((r) => ({ ...r, label: r.day }));
  const dailyColumns = [
    { key: "day", label: "День", type: "date" },
    ...[["revenue", "Выручка"], ["buyer", "По ценам покупателя"], ["net_accrued", "Начислено"],
      ["cogs", "Себестоимость"], ["ads", "Реклама"], ["external", "Внешние расходы"],
      ["tax", "Налог"], ["profit", "Чистая прибыль"], ["stock_cost", "Себестоимость остатков"]].map(([key, label]) => ({ key, label, type: "money", render: (row) => row[key] == null ? "—" : moneyFmt(row[key]) })),
    { key: "stock", label: "Остаток, шт.", type: "number" },
    { key: "tax_status", label: "Налог", render: (r) => r.tax_status === "estimated" ? "Предварительно" : r.tax_status === "allocated_report" ? "По отчёту, распределён" : "Не настроен" },
  ];

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
        <MetricCard label={t("dashboard.revenue")} value={state.pnl ? moneyFmt(sum(daily, "revenue")) : "—"} subvalue={period} className="col-span-2" />
        <MetricCard label={t("dashboard.salesQty")} value={state.pnl ? numberFmt(sum(daily, "qty")) : "—"} subvalue={`${t("dashboard.sumQty")} ${period}`} />
        <MetricCard label={t("dashboard.adCost")} value={state.pnl ? moneyFmt(sum(daily, "ads")) : "—"} subvalue={period} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {state.balance.map((b) => (
          <MetricCard
            key={`${b.marketplace}|${b.account_id}`}
            label={`${t("finance.balance")} ${marketplaceName(b.marketplace)}`}
            value={moneyFmt(b.balance)}
            subvalue={balanceCaption({ ...b, for_withdraw: null }, t)}
            accent="success"
          />
        ))}
        <MetricCard label={t("finance.netAccrued")} value={state.pnl ? moneyFmt(sum(daily, "net_accrued")) : "—"} subvalue={period} accent="success" />
        <MetricCard label="Чистая прибыль после налогов" value={profit.calculated ? `${profit.estimated ? "≈ " : ""}${moneyFmt(profit.net)}` : "—"}
          accent={profit.calculated ? (profit.net >= 0 ? "success" : "error") : undefined}
          subvalue={<>
            <span>{period}</span>
            <span className="block mt-1">{!profit.available ? "Нет данных P&L или доступа к ним" : profit.estimated ? "Предварительно: налог по ценам покупателя за вычетом возвратов. Пересчитается после получения полного отчёта" : "После себестоимости, удержаний, рекламы, внешних расходов и налога"}</span>
            {profit.available && profit.estimated && <span className="block mt-1">До налога: {moneyFmt(profit.beforeTax)}</span>}
            {profit.available && <span className="block mt-1">Внешние расходы учтены: {moneyFmt(profit.expenses)}{(searchParams.get("marketplace") || searchParams.get("accountId")) ? " (общие по организации)" : ""}</span>}
          </>} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <MetricCard label={t("dashboard.stockUnits")} value={stockRows.length ? numberFmt(sum(stockRows, "stock_end")) : "—"} subvalue={<>
          <span>На {profitTo}; {numberFmt(state.stocks.length)} {t("dashboard.items")}</span>
          <span className="block mt-4">{t("dashboard.stockCost")}</span>
          <span className="block mt-1 text-xl font-bold tabular-nums text-[var(--color-on-surface)]">{stockValuationAvailable ? moneyFmt(sum(stockRows, "stock_cost_rub")) : "—"}</span>
          {!stockValuationAvailable && stockRows.length > 0 && <span className="block mt-1">Данные себестоимости временно недоступны</span>}
          {stockValuationAvailable && uncostedStockUnits > 0 && <span className="block mt-1 text-[var(--color-warning)]">{t("dashboard.stockWithoutCost")}: {numberFmt(uncostedStockUnits)}</span>}
        </>} className="lg:col-span-1" />
        <div className="lg:col-span-3">
          <AreaChartCard title={`${t("dashboard.revenueTrend")} ${period}`} data={dailyChart} dataKey="revenue" name={t("dashboard.revenue")} currency />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <div className="lg:col-span-3">
          <AreaChartCard title={`${t("dashboard.adSpendTrend")} ${period}`} data={dailyChart} dataKey="ads" name={t("dashboard.adCost")} color="var(--color-warning)" currency />
        </div>
        <MetricCard label={t("dashboard.stockItems")} value={numberFmt(new Set(state.stocks.map(r => r.product_id)).size)} subvalue={t("dashboard.uniqueProducts")} />
      </div>

      <AreaChartCard title={`Чистая прибыль по дням ${period}`} data={dailyChart} dataKey="profit" name="Чистая прибыль" color="var(--color-success)" currency />
      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold mb-3">Показатели по дням</h3>
        {!state.pnl && <p className="text-sm">Не удалось загрузить дневной расчёт прибыли.</p>}
        {state.pnl?.notes?.map((note) => <p key={note} className="text-xs text-[var(--color-on-surface-variant)] mb-2">{note}</p>)}
        {daily.some((r) => r.missing_costs > 0) && <p className="text-sm text-[var(--color-warning)] mb-2">Часть товаров без себестоимости: прибыль предварительная.</p>}
        <DataTable rows={daily} columns={dailyColumns} stateKey="dashboard-daily" />
      </section>

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-3">{t("dashboard.topProducts")} {period}</h3>
        <DataTable rows={topProducts} filterable={false} preferredColumns={["rank", "image_url", "title", "offer_id", "marketplace", "product_id", "qty", "revenue", "returns_qty", "payout"]} />
      </section>
    </div>
  );
}
